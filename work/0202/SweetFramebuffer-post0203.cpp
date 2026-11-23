/*
 * Built-in IOMobileFramebuffer for SWEET: the ABL's continuous-splash
 * framebuffer (1080x2400 a8r8g8b8 in RAM, the panel scans it out by
 * itself) as the main display, driven by CoreAnimation's CPU renderer.
 *
 * IOMobileFramebuffer.framework (iOS 16.7) counts /arm-io children with
 * device_type "display-subsystem", waits for that many services matching
 * IOServiceMatching("IOMobileFramebuffer"), opens each with type 0 and
 * reads canvas-width/canvas-height from the service's provider. The class
 * here (AppleCLCD, an IOMobileFramebuffer) matches the /arm-io/disp0 nub.
 *
 * User client selectors used by CoreAnimation:
 *   3  GetLayerDefaultSurface [layer, ?] -> [IOSurface port name]
 *   4  SwapBegin -> [swap id]
 *   5  SwapEnd, struct 0x46c: +0x50 swap id, +0x54 IOSurface id per layer
 *      (4 layers), +0x64 rect a / +0xc4 rect b per layer (int x,y,w,h),
 *      +0x104 enabled layer mask
 *   6  SwapWait, 7 GetID, 8 GetDisplaySize -> [w, h],
 *   12 RequestPowerChange [state]: 0 = display off (backboardd, power
 *      button / auto-lock), else on. Off fades the panel out over a few
 *      vsyncs (halving each pixel) and keeps it black until on again;
 *      the panel itself stays powered (AMOLED black pixels are off).
 *   18 IsMainDisplay,
 *   28 GetDotPitch, 72 Enable/DisableNotifications [func, refcon, type, 0]
 * Everything else is accepted and logged once.
 *
 * SwapEnd copies the enabled layers' surfaces into the panel memory (no
 * scaling, CPU copy). Vsync (notification type 5) is a 60 Hz timer that
 * sends (count, mach_absolute_time, 0) as 32-bit halves to clients that
 * enabled it, through the port they registered (IOConnectSetNotificationPort).
 *
 * The panel memory itself is published as an IOSurface and returned as the
 * default framebuffer surface. The kernel text console keeps drawing over
 * the GUI by default: boot-arg sweetfb_noconsole=1 (or a5fb_noconsole=1) stops
 * drawing it from the first swap on (it still reaches the persistent log;
 * panics draw).
 */
#include "SweetSurface.h"

extern "C" int sweet_console_muted;     /* osfmk/console/serial_console.c */

#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/system.h>
#include <pexpert/pexpert.h>
#include <pexpert/arm64/board_config.h>
#include <kern/clock.h>
#include <sys/proc.h>

#if defined(ARM64_BOARD_CONFIG_PRA)
/* bsd/dev/prague_gpu.c: the Mali-T830 scales a surface to the whole panel
 * (the 0235 herolte analog; boot-arg sweetfb_gpu=1, the CPU row copy stays
 * the fallback whenever the GPU path returns false). */
extern "C" int prague_gpu_present_slot(uint32_t id, uint64_t first_pa);
extern "C" int prague_gpu_present_map(uint32_t id, const uint64_t *pages, unsigned n);
extern "C" bool prague_gpu_present_draw(int s, uint32_t off, uint32_t stride, uint32_t w, uint32_t h);
#define SWEET_FB_GPU_MAX_PAGES 2048     /* one 8 MiB GPU slot */
#endif

enum {
	kSweetFBGetLayerDefaultSurface  = 3,
	kSweetFBSwapBegin               = 4,
	kSweetFBSwapEnd                 = 5,
	kSweetFBSwapWait                = 6,
	kSweetFBGetID                   = 7,
	kSweetFBGetDisplaySize          = 8,
	kSweetFBRequestPowerChange      = 12,
	kSweetFBIsMainDisplay           = 18,
	kSweetFBGetDotPitch             = 28,
	kSweetFBNotifications           = 72,
};

#define SWEET_FB_SWAP_REC_SIZE          0x46c
#define SWEET_FB_LAYERS                 4
#define SWEET_FB_NOTIFY_TYPES           8
#define SWEET_FB_NOTIFY_VSYNC           5
#define SWEET_FB_VSYNC_US               16667
#if defined(ARM64_BOARD_CONFIG_A5XELTE)
#define SWEET_FB_DOT_PITCH              424     /* 1080 pixels across 5.2 inches */
#else
#define SWEET_FB_DOT_PITCH              458     /* ppi, as the iPhone X panel */
#endif
/*
 * The iOS userland only has status bar / layout data for real iPhone
 * screens (UIKit: "No status bar visual provider for screen", the red
 * rdar://45025538 bar for 360x800 points). The display is therefore
 * presented as the iPhone X panel, 1125x2436 (375x812 points @3x), and the
 * centered 1080x2400 part of it is shown on the 1080x2400 panel.
 * Boot-arg sweetfb_native=1 presents the real panel size instead.
 */
#define SWEET_FB_LOGICAL_W              1125
#define SWEET_FB_LOGICAL_H              2436
#define SWEET_FB_FORMAT_BGRA            0x42475241

class IOMobileFramebuffer : public IOService {
	OSDeclareDefaultStructors(IOMobileFramebuffer);
};

OSDefineMetaClassAndStructors(IOMobileFramebuffer, IOService);

class IOMobileFramebufferUserClient;

class AppleCLCD : public IOMobileFramebuffer {
	OSDeclareDefaultStructors(AppleCLCD);

	IOWorkLoop         *fWorkLoop;
	IOTimerEventSource *fVsync;
	uint64_t            fVsyncCount;

	static void vsyncFired(OSObject *owner, IOTimerEventSource *sender);

public:
	uint64_t      fPhys;
	uint32_t      fWidth, fHeight, fRowBytes;
	uint32_t      fLogicalW, fLogicalH;     /* size reported to userland */
	int32_t       fOffX, fOffY;             /* logical origin of the panel */
	uintptr_t     fPixels;          /* kernel mapping of the panel memory */
	IOMemoryMap  *fMap;
	SweetSurface *fSurface;         /* the panel memory as an IOSurface */
	IOLock       *fLock;            /* swaps and client list */
	OSArray      *fClients;
	uint32_t      fSwapID;
	bool          fConsolePaused;
#if defined(ARM64_BOARD_CONFIG_PRA)
	bool          fGpu;             /* sweetfb_gpu: scaled by the Mali, bilinear */
#endif
	uint8_t       fPending[SWEET_FB_SWAP_REC_SIZE];     /* latest swap, not yet shown */
	bool          fDirty;
	uint32_t      fFlushTicks;    /* vsync ticks between panel copies */
	bool          fPowerOff;      /* RequestPowerChange(0) */
	uint32_t      fFadeStep;      /* fade-out steps done while off */
	uint32_t      fPowerReq;      /* 0201: RequestPowerChange calls seen */
	bool          fUserlandOff;   /* 0201: what userland last asked for */
	IOLock       *fPresentLock;   /* one panel copy at a time */
	uint64_t      fLastPresent;   /* mach_absolute_time of the last copy */
	uint64_t      fMinGap;        /* 1/hz in timebase ticks */

	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	void addClient(IOMobileFramebufferUserClient *client);
	void removeClient(IOMobileFramebufferUserClient *client);
	void notifyAll(uint32_t type, const uint64_t *values, uint32_t count);
	void swap(const uint8_t *rec);
	void present(const uint8_t *rec);
#if defined(ARM64_BOARD_CONFIG_PRA)
	bool gpuPresent(SweetSurface *s, int32_t sx, int32_t sy, int32_t w, int32_t h);
#endif
};

OSDefineMetaClassAndStructors(AppleCLCD, IOMobileFramebuffer);

class IOMobileFramebufferUserClient : public IOUserClient {
	OSDeclareDefaultStructors(IOMobileFramebufferUserClient);

public:
	AppleCLCD          *fFB;
	task_t              fTask;
	mach_port_t         fPort;
	io_user_reference_t fFunc[SWEET_FB_NOTIFY_TYPES];
	io_user_reference_t fRefcon[SWEET_FB_NOTIFY_TYPES];

	bool initWithTask(task_t owningTask, void *securityID, UInt32 type) APPLE_KEXT_OVERRIDE;
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	IOReturn registerNotificationPort(mach_port_t port, UInt32 type,
	    io_user_reference_t refCon) APPLE_KEXT_OVERRIDE;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target,
	    void *reference) APPLE_KEXT_OVERRIDE;
	void notify(uint32_t type, const uint64_t *values, uint32_t count);
};

OSDefineMetaClassAndStructors(IOMobileFramebufferUserClient, IOUserClient);

bool
AppleCLCD::start(IOService *provider)
{
	PE_Video video;

	if (!IOService::start(provider)) {
		return false;
	}
	PE_current_console(&video);
#if defined(ARM64_BOARD_CONFIG_A5XELTE)
	/* The loader's DECON handoff scans out this physical XRGB8888 buffer.
	 * It does not fill boot_args.Video, so PE_current_console is empty.
	 * Keep the physical address out of the donor path. */
	fPhys = A5_FB_PHYS;
	fWidth = A5_FB_WIDTH;
	fHeight = A5_FB_HEIGHT;
	fRowBytes = A5_FB_STRIDE;
#else
	fPhys = video.v_baseAddr;
	fWidth = (uint32_t)video.v_width;
	fHeight = (uint32_t)video.v_height;
	fRowBytes = (uint32_t)video.v_rowBytes;
#endif
	if (fPhys == 0 || fWidth == 0 || fHeight == 0 || fRowBytes < fWidth * 4) {
		IOLog("SWEET FB: no boot framebuffer\n");
		return false;
	}
	int native = 0;
	PE_parse_boot_argn("sweetfb_native", &native, sizeof(native));
	fLogicalW = fWidth;
	fLogicalH = fHeight;
#if defined(DREAMLTE)
	if (!native) {
		fLogicalW = SWEET_FB_LOGICAL_W;
		fLogicalH = SWEET_FB_LOGICAL_H;
	}
#elif !defined(ARM64_BOARD_CONFIG_A5XELTE)
	if (!native && fWidth <= SWEET_FB_LOGICAL_W && fHeight <= SWEET_FB_LOGICAL_H) {
		fLogicalW = SWEET_FB_LOGICAL_W;
		fLogicalH = SWEET_FB_LOGICAL_H;
	}
#endif
	fOffX = (int32_t)(fLogicalW - fWidth) / 2;
	fOffY = (int32_t)(fLogicalH - fHeight) / 2;
#if defined(ARM64_BOARD_CONFIG_PRA)
	/* sweetfb_gpu=1: full-screen frames go through the Mali instead
	 * (bsd/dev/prague_gpu.c), bilinear; the CPU row copy stays the
	 * fallback. */
	int gpu = 0;
	PE_parse_boot_argn("sweetfb_gpu", &gpu, sizeof(gpu));
	fGpu = gpu != 0;
#endif
	fLock = IOLockAlloc();
	fClients = OSArray::withCapacity(4);
	fSurface = sweet_surface_create_physical(fPhys, fWidth, fHeight, fRowBytes, SWEET_FB_FORMAT_BGRA);
	fPixels = fSurface != NULL ? fSurface->kernelAddress() : 0;
	fWorkLoop = IOWorkLoop::workLoop();
	if (fLock == NULL || fClients == NULL || fPixels == 0 || fWorkLoop == NULL) {
		IOLog("SWEET FB: setup failed\n");
		OSSafeReleaseNULL(fSurface);    /* stays published: also held by the table */
		OSSafeReleaseNULL(fWorkLoop);
		return false;
	}
	fVsync = IOTimerEventSource::timerEventSource(this, &AppleCLCD::vsyncFired);
	if (fVsync == NULL || fWorkLoop->addEventSource(fVsync) != kIOReturnSuccess) {
		IOLog("SWEET FB: no vsync timer\n");
		return false;
	}
	uint32_t hz = 10;
	PE_parse_boot_argn("sweetfb_hz", &hz, sizeof(hz));
	fFlushTicks = (hz == 0 || hz >= 60) ? 1 : 60 / hz;
	fMinGap = 26000000ULL / (hz == 0 ? 60 : hz);     /* 26 MHz timebase */
	fPresentLock = IOLockAlloc();
	if (fPresentLock == NULL) {
		return false;
	}
	/* 0201: fPowerOff/fFadeStep still rely on the zeroed allocation (as
	 * they always did); the request counter and the last userland request
	 * are set here because present() reads them. */
	fPowerReq = 0;
	fUserlandOff = false;
	fVsync->setTimeoutUS(SWEET_FB_VSYNC_US);

	setProperty(kIOUserClientClassKey, "IOMobileFramebufferUserClient");
	setProperty("external", false);
	setProperty("DisplayPipePlaneBaseAlignment", 64ULL, 32);
	registerService();
	IOLog("SWEET FB: AppleCLCD %ux%u stride %u at 0x%llx, default surface %u, presented as %ux%u\n",
	    fWidth, fHeight, fRowBytes, fPhys, fSurface->id, fLogicalW, fLogicalH);
	return true;
}

void
AppleCLCD::vsyncFired(OSObject *owner, IOTimerEventSource *sender)
{
	AppleCLCD *fb = (AppleCLCD *)owner;
	uint64_t now = mach_absolute_time();
	uint64_t count = ++fb->fVsyncCount;
	uint64_t values[6] = {
		(uint32_t)count, (uint32_t)(count >> 32),
		(uint32_t)now, (uint32_t)(now >> 32),
		0, 0,
	};

	IOLockLock(fb->fLock);
	for (unsigned int i = 0; i < fb->fClients->getCount(); i++) {
		IOMobileFramebufferUserClient *client =
		    (IOMobileFramebufferUserClient *)fb->fClients->getObject(i);
		client->notify(SWEET_FB_NOTIFY_VSYNC, values, 6);
	}
	if (fb->fPowerOff) {
		/* Fade out: halve every channel each vsync, then black, then idle. */
		uint32_t step = fb->fFadeStep;
		if (step <= 6) {
			fb->fFadeStep = step + 1;
		}
		IOLockUnlock(fb->fLock);
		if (step <= 6) {
			for (uint32_t y = 0; y < fb->fHeight; y++) {
				volatile uint32_t *row = (volatile uint32_t *)(fb->fPixels + (uint64_t)y * fb->fRowBytes);
				for (uint32_t x = 0; x < fb->fWidth; x++) {
					row[x] = step < 6 ? (row[x] >> 1) & 0x7f7f7f7f : 0;
				}
			}
		}
		sender->setTimeoutUS(SWEET_FB_VSYNC_US);
		return;
	}
	bool flush = fb->fDirty && (count % fb->fFlushTicks) == 0;
	uint8_t *rec = NULL;
	if (flush) {
		rec = (uint8_t *)IOMallocData(SWEET_FB_SWAP_REC_SIZE);
		if (rec != NULL) {
			memcpy(rec, fb->fPending, SWEET_FB_SWAP_REC_SIZE);
			fb->fDirty = false;
		}
	}
	IOLockUnlock(fb->fLock);
	if (rec != NULL) {
		fb->present(rec);
		IOFreeData(rec, SWEET_FB_SWAP_REC_SIZE);
	}
	sender->setTimeoutUS(SWEET_FB_VSYNC_US);
}

void
AppleCLCD::addClient(IOMobileFramebufferUserClient *client)
{
	IOLockLock(fLock);
	fClients->setObject(client);
	IOLockUnlock(fLock);
}

/*
 * 0203: notify() for one type to every open client, under the lock. notify()
 * itself returns silently when the client has no function registered for the
 * type (fFunc[type] == 0), so a type with no subscriber costs nothing.
 */
void
AppleCLCD::notifyAll(uint32_t type, const uint64_t *values, uint32_t count)
{
	IOLockLock(fLock);
	for (unsigned int i = 0; i < fClients->getCount(); i++) {
		IOMobileFramebufferUserClient *client =
		    (IOMobileFramebufferUserClient *)fClients->getObject(i);
		client->notify(type, values, count);
	}
	IOLockUnlock(fLock);
}

void
AppleCLCD::removeClient(IOMobileFramebufferUserClient *client)
{
	IOLockLock(fLock);
	unsigned int i = fClients->getNextIndexOfObject(client, 0);
	if (i != (unsigned int)-1) {
		fClients->removeObject(i);
	}
	IOLockUnlock(fLock);
}

static uint32_t
get32(const uint8_t *p, uint32_t off)
{
	uint32_t v;
	memcpy(&v, p + off, 4);
	return v;
}

#if defined(DREAMLTE)
/*
 * Boot 31 video: torn frames (top half of one screen, bottom of the
 * next). DECON_F fetches the panel memory at 60 Hz (boot 30 probe: 30
 * frame-done events per 0.5 s) while we copy into it. Start each copy
 * right after a frame-done (INTERRUPT_PENDING 0x4c bit 13, source
 * enabled in INTERRUPT_ENABLE 0x40; the SPI is not routed), so the copy
 * runs ahead of the next fetch.
 */
extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
static vm_offset_t sweet_fb_decon;

static void
sweet_fb_wait_frame_done(void)
{
	if (sweet_fb_decon == 0) {
		sweet_fb_decon = ml_io_map(0x12860000, 0x1000);
		if (sweet_fb_decon == 0) {
			return;
		}
		*(volatile uint32_t *)(sweet_fb_decon + 0x40) |= (1u << 13) | 1u;
	}
	volatile uint32_t *pend = (volatile uint32_t *)(sweet_fb_decon + 0x4c);
	*pend = 1u << 13;
	for (int i = 0; i < 200 && !(*pend & (1u << 13)); i++) {
		IODelay(100);
	}
}
#endif

static uint32_t sweet_fb_swaps_logged;
static uint64_t sweet_fb_swap_count;

/* Copy each enabled layer's surface into the panel memory (no scaling). */
/*
 * A swap only records the frame: copying 10 MB into the panel on every
 * swap (backboardd presents at 60 Hz) took the whole CPU. The vsync timer
 * shows the latest frame every fFlushTicks ticks (boot-arg sweetfb_hz,
 * default 10 Hz).
 */
void
AppleCLCD::swap(const uint8_t *rec)
{
	IOLockLock(fLock);
	memcpy(fPending, rec, SWEET_FB_SWAP_REC_SIZE);
	fDirty = true;
	uint64_t now = mach_absolute_time();
	bool copyNow = !fPowerOff && now - fLastPresent >= fMinGap;
	if (copyNow) {
		fDirty = false;
		fLastPresent = now;
	}
	IOLockUnlock(fLock);
	if (copyNow) {
		present(rec);
	}
	if ((++sweet_fb_swap_count % 1000) == 0) {
		IOLog("SWEET FB: %llu swaps\n", sweet_fb_swap_count);
	}
}

void
AppleCLCD::present(const uint8_t *rec)
{
	uint32_t mask = get32(rec, 0x104);
	IOLockLock(fPresentLock);
#if defined(DREAMLTE)
	sweet_fb_wait_frame_done();
#endif


	if (!fConsolePaused) {
		int quiet = 0;
		fConsolePaused = true;
		/* PRA is compiled with both ARM64_BOARD_CONFIG_PRA and
		 * ARM64_BOARD_CONFIG_A5XELTE (0130), so this branch used to look
		 * only for a5fb_noconsole while the comment above and every image
		 * cmdline said sweetfb_noconsole - and the console kept drawing
		 * over the GUI. Accept either name, on every board. */
		bool have = PE_parse_boot_argn("sweetfb_noconsole", &quiet, sizeof(quiet));
		if (!have) {
			have = PE_parse_boot_argn("a5fb_noconsole", &quiet, sizeof(quiet));
		}
		if (have && quiet != 0) {
			/* Not PE_initialize_console(kPEDisableScreen): its console switch
			 * writes the read-only-late cons_ops_index and panics. */
			sweet_console_muted = 1;
		}
	}

	for (uint32_t layer = 0; layer < SWEET_FB_LAYERS; layer++) {
		uint32_t id = get32(rec, 0x54 + 4 * layer);
		const uint8_t *a = rec + 0x64 + 16 * layer;
		const uint8_t *b = rec + 0xc4 + 16 * layer;
		int32_t sx = (int32_t)get32(a, 0), sy = (int32_t)get32(a, 4);
		int32_t dx = (int32_t)get32(b, 0), dy = (int32_t)get32(b, 4);
		int32_t w = (int32_t)get32(b, 8), h = (int32_t)get32(b, 12);

		if (!(mask & (1u << layer)) || id == 0) {
			continue;
		}
		SweetSurface *s = sweet_surface_copy(id);
		if (sweet_fb_swaps_logged < 16) {
			sweet_fb_swaps_logged++;
			IOLog("SWEET FB: swap %u layer %u surface %u %ux%u fmt 0x%x bpr %u a %d,%d %ux%u b %d,%d %dx%d\n",
			    get32(rec, 0x50), layer, id, s ? s->width : 0, s ? s->height : 0,
			    s ? s->pixelFormat : 0, s ? s->bytesPerRow : 0, sx, sy, get32(a, 8),
			    get32(a, 12), dx, dy, w, h);
		}
		/* 0201: frames still reach the panel while userland believes the
		 * display is off (keep_on swallowed its request): the state split
		 * E3 describes, one line per presented layer. */
		if (fUserlandOff) {
			IOLog("SWEET FB: swap %u while userland-display-off\n", get32(rec, 0x50));
		}
		if (s == NULL || s == fSurface) {
			OSSafeReleaseNULL(s);
			continue;
		}
		uintptr_t src = s->kernelAddress();
		uint32_t bpe = s->bytesPerElement ? s->bytesPerElement : 4;
		if (w <= 0 || h <= 0) {
			w = (int32_t)s->width;
			h = (int32_t)s->height;
		}
		if (sx < 0 || sy < 0) {
			sx = sy = 0;
		}
		if (dx < 0 || dy < 0) {
			dx = dy = 0;
		}
		/* Logical (presented) display coordinates -> panel coordinates. */
		dx -= fOffX;
		dy -= fOffY;
		if (dx < 0) {
			sx -= dx;
			w += dx;
			dx = 0;
		}
		if (dy < 0) {
			sy -= dy;
			h += dy;
			dy = 0;
		}
		if (w > (int32_t)s->width - sx) {
			w = (int32_t)s->width - sx;
		}
		if (h > (int32_t)s->height - sy) {
			h = (int32_t)s->height - sy;
		}
		if (w > (int32_t)fWidth - dx) {
			w = (int32_t)fWidth - dx;
		}
		if (h > (int32_t)fHeight - dy) {
			h = (int32_t)fHeight - dy;
		}
		uint64_t last = (uint64_t)s->offset + (uint64_t)(sy + h - 1) * s->bytesPerRow +
		    (uint64_t)(sx + w) * 4;
		if (w <= 0 || h <= 0 || s->elementWidth != 1 || s->elementHeight != 1 ||
		    s->memory == NULL || last > s->memory->getLength()) {
			src = 0;
		}
#if defined(ARM64_BOARD_CONFIG_PRA)
		/* sweetfb_gpu=1: the Mali draws whole-screen frames scaled to the
		 * panel (prague_gpu.c present slots); anything else keeps the CPU
		 * copy. dx/dy are already panel coordinates here, and PRA presents
		 * the native 1080x1920 panel (no logical scaling), so a full-screen
		 * layer arrives at dx=dy=0 with the panel's size. */
		if (src != 0 && bpe == 4 && fGpu && dx == 0 && dy == 0 &&
		    w == (int32_t)fWidth && h == (int32_t)fHeight && gpuPresent(s, sx, sy, w, h)) {
			s->release();
			continue;
		}
#endif
		if (src != 0 && bpe == 4) {
			for (int32_t y = 0; y < h; y++) {
				memcpy((void *)(fPixels + (uint64_t)(dy + y) * fRowBytes + (uint64_t)dx * 4),
				    (const void *)(src + s->offset + (uint64_t)(sy + y) * s->bytesPerRow + (uint64_t)sx * 4),
				    (size_t)w * 4);
			}
		}
		s->release();
	}
	IOLockUnlock(fPresentLock);
}

bool
IOMobileFramebufferUserClient::initWithTask(task_t owningTask, void *securityID, UInt32 type)
{
	if (!IOUserClient::initWithTask(owningTask, securityID, type)) {
		return false;
	}
	fTask = owningTask;
	return true;
}

bool
IOMobileFramebufferUserClient::start(IOService *provider)
{
	fFB = OSDynamicCast(AppleCLCD, provider);
	if (fFB == NULL || !IOUserClient::start(provider)) {
		return false;
	}
	fFB->addClient(this);
	return true;
}

IOReturn
IOMobileFramebufferUserClient::clientClose(void)
{
	if (fFB != NULL) {
		fFB->removeClient(this);
		IOLockLock(fFB->fLock);
		mach_port_t old = fPort;
		fPort = MACH_PORT_NULL;
		IOLockUnlock(fFB->fLock);
		if (old != MACH_PORT_NULL) {
			releaseNotificationPort(old);
		}
	}
	terminate();
	return kIOReturnSuccess;
}

IOReturn
IOMobileFramebufferUserClient::registerNotificationPort(mach_port_t port, __unused UInt32 type,
    __unused io_user_reference_t refCon)
{
	mach_port_t old;
	IOLockLock(fFB->fLock);
	old = fPort;
	fPort = port;
	IOLockUnlock(fFB->fLock);
	if (old != MACH_PORT_NULL) {
		releaseNotificationPort(old);
	}
	return kIOReturnSuccess;
}

/* Called with the framebuffer lock held. */
void
IOMobileFramebufferUserClient::notify(uint32_t type, const uint64_t *values, uint32_t count)
{
	OSAsyncReference64 ref;

	if (type >= SWEET_FB_NOTIFY_TYPES || fFunc[type] == 0 || fPort == MACH_PORT_NULL) {
		return;
	}
	bzero(ref, sizeof(ref));
	setAsyncReference64(ref, fPort, (mach_vm_address_t)fFunc[type], fRefcon[type], fTask);
	sendAsyncResult64WithOptions(ref, kIOReturnSuccess, (io_user_reference_t *)values, count,
	    kIOUserNotifyOptionCanDrop);
}

static uint64_t sweet_fb_logged;        /* selectors already logged (< 64) */

IOReturn
IOMobileFramebufferUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    __unused IOExternalMethodDispatch *dispatch, __unused OSObject *target,
    __unused void *reference)
{
	IOReturn ret = kIOReturnSuccess;
	uint64_t out[2] = { 0, 0 };
	uint32_t outCount = 0;

	switch (selector) {
	case kSweetFBGetLayerDefaultSurface:
		out[0] = sweet_surface_port_in_task(fFB->fSurface, fTask);
		outCount = 1;
		break;
	case kSweetFBSwapBegin:
		IOLockLock(fFB->fLock);
		out[0] = ++fFB->fSwapID;
		IOLockUnlock(fFB->fLock);
		outCount = 1;
		break;
	case kSweetFBSwapEnd: {
		uint8_t rec[SWEET_FB_SWAP_REC_SIZE];
		if (args->structureInputDescriptor != NULL ||
		    args->structureInputSize < SWEET_FB_SWAP_REC_SIZE) {
			ret = kIOReturnBadArgument;
			break;
		}
		memcpy(rec, args->structureInput, sizeof(rec));
		fFB->swap(rec);
		break;
	}
	case kSweetFBGetID:
		out[0] = 0;
		outCount = 1;
		break;
	case kSweetFBGetDisplaySize:
		out[0] = fFB->fLogicalW;
		out[1] = fFB->fLogicalH;
		outCount = 2;
		break;
	case kSweetFBIsMainDisplay:
		out[0] = 1;
		outCount = 1;
		break;
	case kSweetFBGetDotPitch:
		out[0] = SWEET_FB_DOT_PITCH;
		outCount = 1;
		break;
	case kSweetFBNotifications:
		/* 0201: log EVERY registration call, ahead of the range guard and
		 * outside the once-per-selector log, as 0/0 when the call is short
		 * so a caller with the wrong argument count is visible too. */
		IOLog("SWEET FB: notifyreg type %u func 0x%llx\n",
		    (unsigned)(args->scalarInputCount >= 3 ? args->scalarInput[2] : 0),
		    (unsigned long long)(args->scalarInputCount >= 1 ? args->scalarInput[0] : 0));
		if (args->scalarInputCount >= 3 && args->scalarInput[2] < SWEET_FB_NOTIFY_TYPES) {
			uint32_t type = (uint32_t)args->scalarInput[2];
			IOLockLock(fFB->fLock);
			fFunc[type] = args->scalarInput[0];
			fRefcon[type] = args->scalarInput[1];
			IOLockUnlock(fFB->fLock);
			char name[32];
			proc_selfname(name, sizeof(name));
			IOLog("SWEET FB: %s notifications type %u %s\n", name, type,
			    args->scalarInput[0] ? "on" : "off");
		}
		break;
	case kSweetFBRequestPowerChange:
		if (args->scalarInputCount >= 1) {
			bool off = args->scalarInput[0] == 0;
			int keep_on = 0;
			/* Same dual-name trap as the console mute: accept both. */
			bool have_keep = PE_parse_boot_argn("a5fb_keep_on", &keep_on, sizeof(keep_on));
			if (!have_keep) {
				have_keep = PE_parse_boot_argn("sweetfb_keep_on", &keep_on, sizeof(keep_on));
			}
			/*
			 * 0201: every request is logged, refused or not, because
			 * backboardd asks for display-off on every boot and keep_on
			 * swallowed it silently. keep= tells whether keep_on took the
			 * request away before it was acted on; applied= tells whether
			 * it differed from the current state (it is NOT "was
			 * applied": keep=1 applied=1 is a refused request).
			 */
			IOLog("SWEET FB: powerreq n=%u arg=%llu off=%d keep=%d applied=%d\n",
			    (unsigned)++fFB->fPowerReq, (unsigned long long)args->scalarInput[0],
			    (int)off, (int)(have_keep && keep_on), (int)(off != fFB->fPowerOff));
			fFB->fUserlandOff = off;
			if (off && have_keep && keep_on) {
				IOLog("A5XELTE FB: display-off request ignored (keep_on)\n");
				break;
			}
			IOLockLock(fFB->fLock);
			bool changed = off != fFB->fPowerOff;
			if (off != fFB->fPowerOff) {
				fFB->fPowerOff = off;
				fFB->fFadeStep = 0;
				fFB->fDirty = true;     /* on: redraw the latest frame */
			}
			IOLockUnlock(fFB->fLock);
			IOLog("SWEET FB: display %s\n", off ? "off" : "on");
			if (changed) {
				/*
				 * 0203: publish the read-back so the divergence is
				 * queryable (and backboardd's model can be corrected
				 * the next time it asks), and notify every registered
				 * type: no client registers today (ring65/66 notifyreg
				 * = 0), so this is a free contract — a future
				 * subscriber's type shows up in the 0201 notifyreg log
				 * and its payload can be shaped then. Two words
				 * {off, 0}; vsync subscribers keep the 6-word shape
				 * from vsyncFired.
				 */
				setProperty("DisplayPowerOff",
				    fFB->fPowerOff ? kOSBooleanTrue : kOSBooleanFalse);
				uint64_t pv[2] = { off ? 0 : 1, 0 };
				IOLog("SWEET FB: power change notified (off=%d)\n", (int)off);
				fFB->notifyAll(0, pv, 2);
				fFB->notifyAll(1, pv, 2);
				fFB->notifyAll(2, pv, 2);
				fFB->notifyAll(3, pv, 2);
				fFB->notifyAll(4, pv, 2);
				fFB->notifyAll(SWEET_FB_NOTIFY_VSYNC, pv, 2);
				fFB->notifyAll(6, pv, 2);
				fFB->notifyAll(7, pv, 2);
			}
		}
		break;
	case kSweetFBSwapWait:
	default:
		break;
	}

	for (uint32_t i = 0; i < args->scalarOutputCount; i++) {
		args->scalarOutput[i] = i < outCount ? out[i] : 0;
	}
	if (args->structureOutputDescriptor == NULL && args->structureOutput != NULL) {
		bzero(args->structureOutput, args->structureOutputSize);
	}
	if (selector >= 64 || !(sweet_fb_logged & (1ULL << selector))) {
		if (selector < 64) {
			sweet_fb_logged |= 1ULL << selector;
		}
		char name[32];
		proc_selfname(name, sizeof(name));
		IOLog("SWEET FB: %s sel %u in %u/%u out %u/%u -> 0x%x\n", name, selector,
		    args->scalarInputCount, args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize, ret);
	}
	return ret;
}

#if defined(ARM64_BOARD_CONFIG_PRA)
/*
 * sweetfb_gpu=1: the Mali draws the whole frame scaled to the panel
 * (bsd/dev/prague_gpu.c, herolte 0235's gpuPresent). The surface is mapped
 * into a GPU slot the first time it is shown (its pages; a slot is keyed by
 * IOSurface id and first page). The Mali is not IO-coherent, so the frame
 * is cleaned to the point of coherency first (dc cvac; herolte U:79-88 and
 * the LINUX_HANDOFF section 15.5 non-coherency evidence for this SoC).
 * Called only from present(), which the vsync timer serializes.
 * False: use the CPU copy (also after 8 failures: the GPU stays off).
 */
bool
AppleCLCD::gpuPresent(SweetSurface *s, int32_t sx, int32_t sy, int32_t w, int32_t h)
{
	static uint64_t pages[SWEET_FB_GPU_MAX_PAGES];
	static uint32_t failures;
	if (failures >= 8 || s->memory == NULL) {
		return false;
	}
	IOByteCount len = 0;
	addr64_t pa0 = s->memory->getPhysicalSegment(0, &len, kIOMemoryMapperNone);
	int slot = pa0 ? prague_gpu_present_slot(s->id, pa0 & ~0xfffULL) : -1;
	if (slot < 0 && pa0 != 0) {
		unsigned n = (unsigned)((s->memory->getLength() + 0xfff) / 0x1000);
		bool ok = n <= SWEET_FB_GPU_MAX_PAGES;
		for (unsigned i = 0; ok && i < n; i++) {
			addr64_t pa = s->memory->getPhysicalSegment((IOByteCount)i * 0x1000, &len,
			    kIOMemoryMapperNone);
			ok = pa != 0;
			pages[i] = pa & ~0xfffULL;
		}
		slot = ok ? prague_gpu_present_map(s->id, pages, n) : -1;
	}
	if (slot < 0) {
		failures++;
		return false;
	}
	uint64_t off = (uint64_t)s->offset + (uint64_t)sy * s->bytesPerRow + (uint64_t)sx * 4;
	uintptr_t start = s->kernelAddress() + (uintptr_t)off;
	uintptr_t end = start + (uintptr_t)(h - 1) * s->bytesPerRow + (uintptr_t)w * 4;
	for (uintptr_t p = start & ~(uintptr_t)63; p < end; p += 64) {
		__asm__ volatile ("dc cvac, %0" : : "r" (p) : "memory");
	}
	__asm__ volatile ("dsb sy" ::: "memory");
	if (!prague_gpu_present_draw(slot, (uint32_t)off, s->bytesPerRow, (uint32_t)w, (uint32_t)h)) {
		failures++;
		return false;
	}
	return true;
}
#endif

#endif /* SWEET || A5XELTE */

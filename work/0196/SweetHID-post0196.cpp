/*
 * SWEET: HID event services for the iOS userland (backboardd's HID event
 * system).
 *
 * backboardd watches for IOService objects with HIDServiceSupport = true,
 * opens them with IOServiceOpen type 'esuc' (IOHIDEventServiceUserClient,
 * compiled here from IOHIDFamily-1915.140.3, the version the iOS 16.7
 * userland ships) and reads serialized IOHIDEvents from the user client's
 * shared queue. This file has the minimal IOHIDEventService base class and
 * two services:
 *
 *   SweetHIDButtons  consumer-control keys (power, volume, home)
 *   SweetHIDTouch    the built-in touch screen (digitizer collections)
 *
 * Hardware drivers feed them through the C entry points sweet_hid_key()
 * and sweet_hid_touch(). Boot-arg sweethidtest=N (seconds) presses Home
 * every N seconds, to test the event path without input hardware.
 */
#include <IOKit/IOLib.h>
#include <IOKit/IOService.h>
#include <IOKit/IOTimerEventSource.h>
#include <libkern/c++/OSArray.h>
#include <pexpert/pexpert.h>

#include "IOHIDEventService.h"
#include "IOHIDEventServiceUserClient.h"
#include "IOHIDEvent.h"
#include "IOHIDKeys.h"
#include "IOHIDPrivateKeys.h"
#include "IOHIDUsageTables.h"

extern "C" uint64_t mach_absolute_time(void);

/* One open client: the user client and its event callback. */
class IOHIDEventServiceClient : public OSObject {
	OSDeclareDefaultStructors(IOHIDEventServiceClient);
public:
	bool                       initClient() { return OSObject::init(); }
	IOService                 *client;
	void                      *context;
	IOHIDEventService::Action  action;
};
OSDefineMetaClassAndStructors(IOHIDEventServiceClient, OSObject);

#define super IOService
OSDefineMetaClassAndStructors(IOHIDEventService, IOService);

bool
IOHIDEventService::start(IOService *provider)
{
	if (!super::start(provider)) {
		return false;
	}
	_clientLock = IOLockAlloc();
	_clients = OSArray::withCapacity(2);
	_hidWorkLoop = getWorkLoop();
	if (!_clientLock || !_clients || !_hidWorkLoop) {
		return false;
	}
	_hidWorkLoop->retain();
	_hidGate = IOCommandGate::commandGate(this);
	if (!_hidGate || _hidWorkLoop->addEventSource(_hidGate) != kIOReturnSuccess) {
		return false;
	}

	OSString *transport = getTransport();
	OSString *product = getProduct();
	setProperty(kIOHIDTransportKey, transport);
	setProperty(kIOHIDProductKey, product);
	setProperty(kIOHIDManufacturerKey, "Sweet");
	setProperty(kIOHIDVendorIDKey, getVendorID(), 32);
	setProperty(kIOHIDProductIDKey, getProductID(), 32);
	setProperty(kIOHIDLocationIDKey, (unsigned long long)getProductID(), 32);
	setProperty(kIOHIDReportIntervalKey, getReportInterval(), 32);
	setProperty(kIOHIDPrimaryUsagePageKey, getPrimaryUsagePage(), 32);
	setProperty(kIOHIDPrimaryUsageKey, getPrimaryUsage(), 32);
	setProperty(kIOHIDBuiltInKey, kOSBooleanTrue);
	OSSafeReleaseNULL(transport);
	OSSafeReleaseNULL(product);

	OSDictionary *pair = OSDictionary::withCapacity(2);
	OSArray *pairs = OSArray::withCapacity(1);
	OSNumber *page = OSNumber::withNumber(getPrimaryUsagePage(), 32);
	OSNumber *usage = OSNumber::withNumber(getPrimaryUsage(), 32);
	if (pair && pairs && page && usage) {
		pair->setObject(kIOHIDDeviceUsagePageKey, page);
		pair->setObject(kIOHIDDeviceUsageKey, usage);
		pairs->setObject(pair);
		setProperty(kIOHIDDeviceUsagePairsKey, pairs);
	}
	OSSafeReleaseNULL(pair);
	OSSafeReleaseNULL(pairs);
	OSSafeReleaseNULL(page);
	OSSafeReleaseNULL(usage);

	/* What IOHIDFamily's "IOHIDEventServiceUserClient" personality merges in. */
	setProperty("HIDServiceSupport", kOSBooleanTrue);
	setProperty("IOUserClientClass", "IOHIDEventServiceUserClient");
	return true;
}

void
IOHIDEventService::free(void)
{
	if (_hidGate && _hidWorkLoop) {
		_hidWorkLoop->removeEventSource(_hidGate);
	}
	OSSafeReleaseNULL(_hidGate);
	OSSafeReleaseNULL(_hidWorkLoop);
	OSSafeReleaseNULL(_clients);
	if (_clientLock) {
		IOLockFree(_clientLock);
		_clientLock = NULL;
	}
	super::free();
}

bool
IOHIDEventService::open(IOService *client, IOOptionBits options, void *context, Action action)
{
	IOHIDEventServiceClient *data = OSTypeAlloc(IOHIDEventServiceClient);
	bool ok = false;

	if (data && data->initClient()) {
		data->client = client;
		data->context = context;
		data->action = action;
		ok = super::open(client, options, data);
	}
	OSSafeReleaseNULL(data);
	IOLog("SWEET HID: %s open by %s -> %d\n", getName(), client ? client->getName() : "?", ok);
	return ok;
}

void
IOHIDEventService::close(IOService *forClient, IOOptionBits options)
{
	super::close(forClient, options);
}

bool
IOHIDEventService::handleOpen(IOService *client, IOOptionBits options __unused, void *argument)
{
	IOHIDEventServiceClient *data = OSDynamicCast(IOHIDEventServiceClient, (OSObject *)argument);
	bool ok = false;

	if (!data) {
		return false;
	}
	IOLockLock(_clientLock);
	if (!handleIsOpenLocked(client)) {
		/* Copy on write: dispatchEvent iterates a snapshot without the lock. */
		OSArray *next = OSArray::withArray(_clients, _clients->getCount() + 1);
		if (next && next->setObject(data)) {
			_clients->release();
			_clients = next;
			ok = true;
		} else {
			OSSafeReleaseNULL(next);
		}
	}
	IOLockUnlock(_clientLock);
	return ok;
}

void
IOHIDEventService::handleClose(IOService *client, IOOptionBits options __unused)
{
	IOLockLock(_clientLock);
	OSArray *next = OSArray::withCapacity(_clients->getCount());
	if (next) {
		for (unsigned int i = 0; i < _clients->getCount(); i++) {
			IOHIDEventServiceClient *data = (IOHIDEventServiceClient *)_clients->getObject(i);
			if (data->client != client) {
				next->setObject(data);
			}
		}
		_clients->release();
		_clients = next;
	}
	IOLockUnlock(_clientLock);
}

bool
IOHIDEventService::handleIsOpenLocked(const IOService *client) const
{
	for (unsigned int i = 0; i < _clients->getCount(); i++) {
		IOHIDEventServiceClient *data = (IOHIDEventServiceClient *)_clients->getObject(i);
		if (client == NULL || data->client == client) {
			return true;
		}
	}
	return false;
}

bool
IOHIDEventService::handleIsOpen(const IOService *client) const
{
	IOLockLock(_clientLock);
	bool open = handleIsOpenLocked(client);
	IOLockUnlock(_clientLock);
	return open;
}

void
IOHIDEventService::dispatchEvent(IOHIDEvent *event, IOOptionBits options)
{
	OSArray *clients;

	event->setSenderID(getRegistryEntryID());
	IOLockLock(_clientLock);
	clients = _clients;
	clients->retain();
	IOLockUnlock(_clientLock);

	static uint64_t last_evlog;	/* 0192: 1 s cadence */
	uint64_t evnow = mach_absolute_time();
	if (last_evlog == 0 || evnow - last_evlog >= 1920000ull) {
		last_evlog = evnow;
		printf("SWEET HID: event size=%u sender=0x%llx\n",
		    (unsigned)event->getLength(), getRegistryEntryID());
	}
	for (unsigned int i = 0; i < clients->getCount(); i++) {
		IOHIDEventServiceClient *data = (IOHIDEventServiceClient *)clients->getObject(i);
		if (data->action) {
			(*data->action)(data->client, this, data->context, event, options);
		}
	}
	clients->release();
}

IOHIDEvent *
IOHIDEventService::copyEvent(IOHIDEventType type __unused, IOHIDEvent *matching __unused, IOOptionBits options __unused)
{
	return NULL;
}

IOHIDEvent *
IOHIDEventService::copyMatchingEvent(OSDictionary *matching __unused)
{
	return NULL;
}

IOReturn
IOHIDEventService::setElementValue(UInt32 usagePage __unused, UInt32 usage __unused, UInt32 value __unused)
{
	return kIOReturnUnsupported;
}

IOReturn
IOHIDEventService::setProperties(OSObject *properties)
{
	/* The event system pushes its settings here; nothing to configure. */
	return OSDynamicCast(OSDictionary, properties) ? kIOReturnSuccess : kIOReturnBadArgument;
}

UInt32
IOHIDEventService::getPrimaryUsagePage()
{
	return 0;
}

UInt32
IOHIDEventService::getPrimaryUsage()
{
	return 0;
}

OSString *
IOHIDEventService::getTransport()
{
	return OSString::withCString("SPU");
}

OSString *
IOHIDEventService::getProduct()
{
	return OSString::withCString(getName());
}

UInt32
IOHIDEventService::getVendorID()
{
	return 0x05ac;
}

UInt32
IOHIDEventService::getProductID()
{
	return 0;
}

UInt32
IOHIDEventService::getReportInterval()
{
	return 10000;	/* us */
}

IOReturn
IOHIDEventService::newUserClient(task_t owningTask, void *securityID, UInt32 type,
    OSDictionary *properties, IOUserClient **handler)
{
	IOUserClient *client;

	if (type != kIOHIDEventServiceUserClientType) {
		IOLog("SWEET HID: %s user client type 0x%x unsupported\n", getName(), (unsigned)type);
		return super::newUserClient(owningTask, securityID, type, properties, handler);
	}
	client = OSTypeAlloc(IOHIDEventServiceUserClient);
	if (!client) {
		return kIOReturnNoMemory;
	}
	if (!client->initWithTask(owningTask, securityID, type)) {
		client->release();
		IOLog("SWEET HID: %s user client init refused\n", getName());
		return kIOReturnBadArgument;
	}
	if (!client->attach(this)) {
		client->release();
		return kIOReturnUnsupported;
	}
	if (!client->start(this)) {
		client->detach(this);
		client->release();
		return kIOReturnUnsupported;
	}
	*handler = client;
	return kIOReturnSuccess;
}

/*
 * Buttons. iOS takes the side/volume/home buttons as consumer-control
 * keyboard events (AppleM68Buttons publishes the same usage pair).
 */
class SweetHIDButtons : public IOHIDEventService {
	OSDeclareDefaultStructors(SweetHIDButtons);
public:
	virtual bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	void key(UInt32 usage, bool down);
protected:
	virtual UInt32 getPrimaryUsagePage() APPLE_KEXT_OVERRIDE { return kHIDPage_Consumer; }
	virtual UInt32 getPrimaryUsage() APPLE_KEXT_OVERRIDE { return kHIDUsage_Csmr_ConsumerControl; }
	virtual UInt32 getProductID() APPLE_KEXT_OVERRIDE { return 1; }
private:
	static void testFired(OSObject *owner, IOTimerEventSource *sender);
	IOTimerEventSource *fTest;
	UInt32 fTestSecs;
	UInt32 fTestCount;
};
OSDefineMetaClassAndStructors(SweetHIDButtons, IOHIDEventService);

/*
 * Touch screen: digitizer collection events with finger children,
 * coordinates normalized to 0..1 like IOHIDEventDriver produces for
 * absolute digitizers.
 */
#define SWEET_TOUCH_FINGERS 10
/*
 * Contacts that start this close to a panel edge (pixels, ~3 mm) carry
 * kIOHIDDigitizerEventFromEdgeTip for their whole life, as Apple's touch
 * firmware reports them. UIKit derives UITouch's edge type from that bit
 * (_UIEventHIDTouchEdgeTypeForHIDEvent); without it there is no home or
 * app-switcher gesture.
 */
#define SWEET_TOUCH_EDGE_PX 48
/*
 * 0196: pratouchswipe=N injects the unlock gesture itself - a one-finger
 * flick up from the bottom edge - N seconds after the touch service starts,
 * then twice more 120 s apart. The down point is 6 px above the panel
 * bottom, inside the 48 px edge band, so the whole contact carries
 * kIOHIDDigitizerEventFromEdgeTip; eight 150 px moves follow every 20 ms.
 * It calls touch(), the same path pra_touch's finger uses, so the kernel
 * half ring61 proved is not bypassed: what it adds is a gesture the lock
 * screen must answer visibly (unlock) with no finger on the panel.
 */
#define SWEET_SWIPE_X     540
#define SWEET_SWIPE_Y0    1914
#define SWEET_SWIPE_DY    150
#define SWEET_SWIPE_MOVES 8
#define SWEET_SWIPE_RUNS  3
class SweetHIDTouch : public IOHIDEventService {
	OSDeclareDefaultStructors(SweetHIDTouch);
public:
	virtual bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	void touch(int finger, bool down, int x, int y);
protected:
	virtual UInt32 getPrimaryUsagePage() APPLE_KEXT_OVERRIDE { return kHIDPage_Digitizer; }
	virtual UInt32 getPrimaryUsage() APPLE_KEXT_OVERRIDE { return kHIDUsage_Dig_TouchScreen; }
	virtual UInt32 getProductID() APPLE_KEXT_OVERRIDE { return 2; }
private:
	IOLock *fLock;
	int fLogicalW, fLogicalH, fOffX, fOffY, fPanelW, fPanelH;
	bool fDown[SWEET_TOUCH_FINGERS];
	bool fEdge[SWEET_TOUCH_FINGERS];
	IOFixed fX[SWEET_TOUCH_FINGERS];
	IOFixed fY[SWEET_TOUCH_FINGERS];
	static void swipeFired(OSObject *owner, IOTimerEventSource *sender);
	IOTimerEventSource *fSwipe;
	UInt32 fSwipeSecs;
	UInt32 fSwipeRuns;
	UInt32 fSwipeStep;
};
OSDefineMetaClassAndStructors(SweetHIDTouch, IOHIDEventService);

static SweetHIDButtons *gSweetButtons;
static SweetHIDTouch *gSweetTouch;
static bool gSweetTouchSelfTest;	/* 0195: pratouchselftest=1 */

bool
SweetHIDButtons::start(IOService *provider)
{
	if (!IOHIDEventService::start(provider)) {
		return false;
	}
	if (PE_parse_boot_argn("sweethidtest", &fTestSecs, sizeof(fTestSecs)) && fTestSecs) {
		fTest = IOTimerEventSource::timerEventSource(this, &SweetHIDButtons::testFired);
		if (fTest && _hidWorkLoop->addEventSource(fTest) == kIOReturnSuccess) {
			fTest->setTimeoutMS(fTestSecs * 1000);
		}
	}
	gSweetButtons = this;
	registerService();
	IOLog("SWEET HID: buttons registered (test every %u s)\n", fTestSecs);
	return true;
}

void
SweetHIDButtons::key(UInt32 usage, bool down)
{
	IOHIDEvent *event = IOHIDEvent::keyboardEvent(mach_absolute_time(), kHIDPage_Consumer, usage, down);

	if (event) {
		IOLog("SWEET HID: key 0x%x %s (%u clients)\n", (unsigned)usage, down ? "down" : "up",
		    _clients ? _clients->getCount() : 0);
		dispatchEvent(event);
		event->release();
	}
}

void
SweetHIDButtons::testFired(OSObject *owner, IOTimerEventSource *sender)
{
	SweetHIDButtons *self = (SweetHIDButtons *)owner;

	/*
	 * Home (Menu) press, then the release 100 ms later; Setup's "Hello"
	 * screen waits for it. Even counts press, odd counts release.
	 */
	bool press = (self->fTestCount & 1) == 0;
	self->key(kHIDUsage_Csmr_Menu, press);
	if (++self->fTestCount < 60) {
		sender->setTimeoutMS(press ? 100 : self->fTestSecs * 1000);
	}
}

bool
SweetHIDTouch::start(IOService *provider)
{
	fLock = IOLockAlloc();
	if (!fLock || !IOHIDEventService::start(provider)) {
		return false;
	}
	int native = 0;
	uint32_t selftest = 0;
	PE_parse_boot_argn("sweetfb_native", &native, sizeof(native));
	if (PE_parse_boot_argn("pratouchselftest", &selftest,
	    sizeof(selftest)) && selftest) {
		gSweetTouchSelfTest = true;
		IOLog("SWEET HID: selftest armed\n");
	}
	/*
	 * 0194: BOTH ARM64_BOARD_CONFIG_PRA and ARM64_BOARD_CONFIG_A5XELTE
	 * are on the PRA compile line, so THIS arm is the one that runs on
	 * PRA. 0193 added fPanelW/fPanelH only to the #else arm, leaving
	 * them zero here - the panel clamp then turned every real touch
	 * into (-1,-1). Initialize the panel in BOTH arms.
	 * PRA's panel is 1080x1920 (pra_touch.c PANEL_X_MAX/PANEL_Y_MAX
	 * and the framebuffer's 1080x1920 swaps), the same geometry as the
	 * working A5 board, so publish that board's real 68x121 mm.
	 */
	int surfaceWmm, surfaceHmm;

#if defined(ARM64_BOARD_CONFIG_A5XELTE)
	fPanelW = 1080;
	fPanelH = 1920;
	fLogicalW = 1080;
	fLogicalH = 1920;
	fOffX = fOffY = 0;
	surfaceWmm = 68;	/* the 1080x1920 panel's real ~68x121 mm */
	surfaceHmm = 121;
	IOLog("SWEET HID: panel arm A5XELTE 1080x1920\n");
#else
	fPanelW = 1080;	/* the PRA panel (the framebuffer's native) */
	fPanelH = 2400;
	fLogicalW = native ? 1080 : 1125;	/* the presented iPhone X display */
	fLogicalH = native ? 2400 : 2436;
	fOffX = (fLogicalW - fPanelW) / 2;
	fOffY = (fLogicalH - fPanelH) / 2;
	surfaceWmm = 132;
	surfaceHmm = 144;
#endif
	/* The digitizer covers the main display (backboardd maps it 1:1). */
	setProperty("DisplayIntegrated", kOSBooleanTrue);
	setProperty("SurfaceWidth", (unsigned long long)((unsigned)surfaceWmm << 16), 32);	/* mm, 16.16 */
	setProperty("SurfaceHeight", (unsigned long long)((unsigned)surfaceHmm << 16), 32);
	gSweetTouch = this;
	registerService();
	/*
	 * 0196: arm the synthetic unlock gesture. The timer runs on the HID
	 * work loop; each step is one touch() call, so the event a finger
	 * would produce is the event this injects. (No "armed" line: start()
	 * runs before the pralog ring exists - ring61 has zero start()
	 * markers. The first swipe logs the interval instead.)
	 */
	fSwipe = NULL;
	fSwipeRuns = 0;
	fSwipeStep = 0;
	fSwipeSecs = 0;
	if (PE_parse_boot_argn("pratouchswipe", &fSwipeSecs, sizeof(fSwipeSecs)) &&
	    fSwipeSecs) {
		fSwipe = IOTimerEventSource::timerEventSource(this,
		    &SweetHIDTouch::swipeFired);
		if (fSwipe && _hidWorkLoop->addEventSource(fSwipe) == kIOReturnSuccess) {
			fSwipe->setTimeoutMS(fSwipeSecs * 1000);
		}
	}
	IOLog("SWEET HID: surface %ux%u mm panel %ux%u\n",
	    surfaceWmm, surfaceHmm, fPanelW, fPanelH);
	IOLog("SWEET HID: touch registered\n");
	return true;
}

void
SweetHIDTouch::touch(int finger, bool down, int x, int y)
{
	uint64_t now = mach_absolute_time();
	IOHIDEvent *collection;
	bool any = false;

	if (finger < 0 || finger >= SWEET_TOUCH_FINGERS) {
		return;
	}
	x = x < 0 ? 0 : (x >= fPanelW ? fPanelW - 1 : x);
	y = y < 0 ? 0 : (y >= fPanelH ? fPanelH - 1 : y);

	IOLockLock(fLock);
	bool was = fDown[finger];
	/* Panel pixels -> the presented 1125x2436 display (SweetFramebuffer.cpp). */
	IOFixed nx = (IOFixed)(((int64_t)(x + fOffX) << 16) / fLogicalW);
	IOFixed ny = (IOFixed)(((int64_t)(y + fOffY) << 16) / fLogicalH);
	bool moved = down && (nx != fX[finger] || ny != fY[finger]);
	if (was == down && !moved) {
		IOLockUnlock(fLock);
		return;
	}
	if (!was && down) {
		fEdge[finger] = x < SWEET_TOUCH_EDGE_PX || x > fPanelW - 1 - SWEET_TOUCH_EDGE_PX ||
		    y < SWEET_TOUCH_EDGE_PX || y > fPanelH - 1 - SWEET_TOUCH_EDGE_PX;
	}

	collection = IOHIDEvent::digitizerEvent(now, 0, kIOHIDDigitizerTransducerTypeHand, false, 0, 0, 0);
	if (!collection) {
		IOLockUnlock(fLock);
		return;
	}
	collection->setIntegerValue(kIOHIDEventFieldDigitizerCollection, TRUE);

	UInt32 cmask = 0;
	for (int i = 0; i < SWEET_TOUCH_FINGERS; i++) {
		bool d = (i == finger) ? down : fDown[i];
		if (i != finger && !d) {
			continue;
		}
		IOFixed fx = (i == finger && down) ? nx : fX[i];
		IOFixed fy = (i == finger && down) ? ny : fY[i];
		IOHIDEvent *child = IOHIDEvent::digitizerEvent(now, (UInt32)i + 2, kIOHIDDigitizerTransducerTypeFinger,
		    d, d ? 1 : 0, fx, fy);
		if (!child) {
			continue;
		}
		UInt32 mask = fEdge[i] ? kIOHIDDigitizerEventFromEdgeTip : 0;
		if (i == finger) {
			if (was != down) {
				mask |= kIOHIDDigitizerEventTouch | kIOHIDDigitizerEventRange;
			}
			if (moved) {
				mask |= kIOHIDDigitizerEventPosition;
			}
			if (!was && down) {
				mask |= kIOHIDDigitizerEventIdentity;
			}
		}
		child->setIntegerValue(kIOHIDEventFieldDigitizerIndex, i);
		child->setIntegerValue(kIOHIDEventFieldDigitizerIdentity, i + 2);
		child->setIntegerValue(kIOHIDEventFieldDigitizerTouch, d);
		child->setIntegerValue(kIOHIDEventFieldDigitizerEventMask, mask);
		collection->appendChild(child);
		child->release();
		cmask |= mask;
		any |= d;
	}
	fDown[finger] = down;
	if (down) {
		fX[finger] = nx;
		fY[finger] = ny;
	}
	collection->setFixedValue(kIOHIDEventFieldDigitizerX, nx);
	collection->setFixedValue(kIOHIDEventFieldDigitizerY, ny);
	collection->setIntegerValue(kIOHIDEventFieldDigitizerRange, any);
	collection->setIntegerValue(kIOHIDEventFieldDigitizerTouch, any);
	collection->setIntegerValue(kIOHIDEventFieldDigitizerEventMask, cmask);
	collection->setIntegerValue(kIOHIDEventFieldDigitizerButtonMask, any ? 1 : 0);
	IOLockUnlock(fLock);

	if (was != down) {
		IOLog("SWEET HID: touch %d %s at %d,%d%s\n", finger, down ? "down" : "up", x, y,
		    fEdge[finger] ? " edge" : "");
	}
	dispatchEvent(collection);
	collection->release();
}

/*
 * 0196: one synthetic unlock gesture: down at the bottom edge, eight
 * 150 px steps up every 20 ms, release. Repeated twice at 120 s intervals
 * so a slow SpringBoard launch cannot miss the only window. Every step
 * calls touch(), so the clamp and the edge flag apply exactly as they do
 * for a real finger.
 */
void
SweetHIDTouch::swipeFired(OSObject *owner, IOTimerEventSource *sender)
{
	SweetHIDTouch *self = (SweetHIDTouch *)owner;
	int y;

	if (self->fSwipeStep == 0) {
		self->fSwipeRuns++;
		self->fSwipeStep = 1;
		IOLog("SWEET HID: swipe %u start (interval %u s) at %d,%d\n",
		    self->fSwipeRuns, self->fSwipeSecs,
		    SWEET_SWIPE_X, SWEET_SWIPE_Y0);
		self->touch(0, true, SWEET_SWIPE_X, SWEET_SWIPE_Y0);
		sender->setTimeoutMS(20);
		return;
	}
	if (self->fSwipeStep <= SWEET_SWIPE_MOVES) {
		y = SWEET_SWIPE_Y0 - (int)self->fSwipeStep * SWEET_SWIPE_DY;
		IOLog("SWEET HID: swipe %u move %u/%u at %d,%d\n",
		    self->fSwipeRuns, self->fSwipeStep,
		    (UInt32)(SWEET_SWIPE_MOVES), SWEET_SWIPE_X, y);
		self->touch(0, true, SWEET_SWIPE_X, y);
		self->fSwipeStep++;
		sender->setTimeoutMS(20);
		return;
	}
	y = SWEET_SWIPE_Y0 - SWEET_SWIPE_MOVES * SWEET_SWIPE_DY;
	self->touch(0, false, SWEET_SWIPE_X, y);
	self->fSwipeStep = 0;
	IOLog("SWEET HID: swipe %u release at %d,%d\n", self->fSwipeRuns,
	    SWEET_SWIPE_X, y);
	if (self->fSwipeRuns >= SWEET_SWIPE_RUNS) {
		IOLog("SWEET HID: swipe selftest done\n");
		return;
	}
	sender->setTimeoutMS(120 * 1000);
}

/* key: 0 power (side button), 1 volume up, 2 volume down, 3 home */
extern "C" void
sweet_hid_key(int key, int down)
{
	static const UInt32 usages[] = {
		kHIDUsage_Csmr_Power, kHIDUsage_Csmr_VolumeIncrement,
		kHIDUsage_Csmr_VolumeDecrement, kHIDUsage_Csmr_Menu,
	};

	if (gSweetButtons && key >= 0 && key < (int)(sizeof(usages) / sizeof(usages[0]))) {
		gSweetButtons->key(usages[key], down != 0);
	}
}

extern "C" void
sweet_hid_touch(int finger, int down, int x, int y)
{
	if (gSweetTouch) {
		gSweetTouch->touch(finger, down != 0, x, y);
	}
}

/*
 * 0195: one-shot synthetic touch, called by the user client after the
 * touch queue is mapped. This bypasses pra_touch and the IC: it tests
 * the 0194 panel clamp and the SweetHID queue with an out-of-bounds raw
 * point (2000,3000) even when the digitizer reports nothing. The clamp
 * must turn it into 1079,1919; zeroed dims would give -1,-1. The svc
 * check keeps the SweetHIDButtons queue map from firing it.
 */
extern "C" void
sweet_hid_touch_selftest(IOHIDEventService *svc)
{
	if (!gSweetTouch || svc != gSweetTouch || !gSweetTouchSelfTest) {
		return;
	}
	gSweetTouchSelfTest = false;
	IOLog("SWEET HID: selftest raw 2000,3000\n");
	gSweetTouch->touch(0, true, 2000, 3000);
	gSweetTouch->touch(0, false, 2000, 3000);
}

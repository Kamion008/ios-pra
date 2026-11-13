/* SPDX-License-Identifier: GPL-2.0-only
 * PRA-LX1 (hi6250 / Kirin 655) EL1 loader for the SWEETXNU payload.
 *
 * The bootloader runs this from the stock kernel load address with the MMU
 * off and x0 = live DTB. It copies the payload's segments to the XNU window
 * in the upper RAM bank, places the ADT and boot_args above the kernel, and
 * enters XNU with translation, D-cache and I-cache off.
 *
 * Payload format and the boot_args layout are the donor's (mkpayload.py v1);
 * only the RAM window and the payload source differ:
 *   - the donor reads the payload from the bootloader initrd;
 *   - PRA embeds it at __payload_start (0x500000) because the `kernel`
 *     partition boot path is the only one fastboot allows and it has no
 *     ramdisk in the stock image.
 *
 * The window starts at 0x88000000, not 0x80000000: /proc/iomem shows a
 * 32 KiB hole at 0x87b00000..0x87b07fff, and boot_args has a single
 * contiguous physBase/memSize pair, so the hole must stay outside it.
 */
#include <stdint.h>
#include "console.h"
#include "linux_boot.h"

#define RAM_BASE 0x88000000UL
/* 1 GiB window = the first step up from the donor's 512 MiB. The loader only
 * bounds-checks against this; the real size is the payload's mem_size, which
 * mkpayload.py copies from the ADT. Keep in sync with dram-size in
 * tools/mkadt_pra.py. Ceiling for one contiguous window is 0xe0000000. */
#define RAM_END  0xC8000000UL
#define PAGE_SIZE 4096UL
#define BOOT_LINE_LENGTH 608

/* Bootloader splash scanout, confirmed by the diagnostic shim (red flood). */
#define FB_BASE      0x5D000000UL
#define FB_WIDTH     1080u
#define FB_HEIGHT    1920u
#define FB_STRIDE_PX 1080u

struct payload_seg {
	uint64_t vmaddr, vmsize, file_off, file_size;
};

struct payload {
	char magic[8];
	uint32_t version, nsegs;
	uint64_t virt_base, entry_va, adt_off, adt_size, kernel_end;
	uint64_t phys_base, mem_size;
	char cmdline[BOOT_LINE_LENGTH];
	struct payload_seg segs[];
};

struct boot_video {
	uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth;
};

struct boot_args {
	uint16_t Revision, Version;
	uint64_t virtBase, physBase, memSize, topOfKernelData;
	struct boot_video Video;
	uint32_t machineType;
	uint64_t deviceTreeP;
	uint32_t deviceTreeLength;
	char CommandLine[BOOT_LINE_LENGTH];
	uint64_t bootFlags, memSizeActual;
};

_Static_assert(__builtin_offsetof(struct payload, segs) == 0x2a8,
               "payload layout");
_Static_assert(__builtin_offsetof(struct boot_args, CommandLine) == 108,
               "boot_args layout");
_Static_assert(sizeof(struct boot_args) == 736, "boot_args size");

extern uint8_t __payload_start[];

/* build-xnu.sh overwrites this with the number of payload bytes appended at
 * __payload_start. The sentinel means the build did not patch it, in which
 * case the loader falls back to the DTB address as the upper bound. */
volatile uint64_t pra_payload_size = 0x5041594c4f4144ULL;	/* "PAYLOAD" */

void pra_jump_mmu_off(uintptr_t entry, uintptr_t boot_args)
	__attribute__((noreturn));

static void zero_bytes(uintptr_t dst, uint64_t size)
{
	volatile uint8_t *d = (volatile uint8_t *)dst;
	for (uint64_t i = 0; i < size; ++i)
		d[i] = 0;
}

static void copy_bytes(uintptr_t dst, uintptr_t src, uint64_t size)
{
	volatile uint8_t *d = (volatile uint8_t *)dst;
	volatile const uint8_t *s = (volatile const uint8_t *)src;
	for (uint64_t i = 0; i < size; ++i)
		d[i] = s[i];
}

static void clean_bytes(uintptr_t start, uintptr_t end)
{
	uint64_t ctr;
	__asm__ volatile("mrs %0, CTR_EL0" : "=r" (ctr));
	uintptr_t line = 4UL << ((ctr >> 16) & 0xf);
	for (uintptr_t p = start & ~(line - 1); p < end; p += line)
		__asm__ volatile("dc cvac, %0" : : "r" (p) : "memory");
	__asm__ volatile("dsb sy" : : : "memory");
}

static int magic_ok(const char *value)
{
	const char *want = "SWEETXNU";
	for (unsigned i = 0; i < 8; ++i)
		if (value[i] != want[i])
			return 0;
	return 1;
}

static uintptr_t align_page(uintptr_t value)
{
	return (value + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1);
}

static void halt(void)
{
	con_puts("HALT\n");
	for (;;)
		__asm__ volatile("wfe");
}

void pra_main(uintptr_t dtb)
{
	uint64_t el, sctlr;

	fb_attach(FB_BASE, FB_WIDTH, FB_HEIGHT, FB_STRIDE_PX);
	fb_clear(0x00101018);
	con_puts("PRA XNU loader\n");

	__asm__ volatile("mrs %0, CurrentEL" : "=r" (el));
	__asm__ volatile("mrs %0, SCTLR_EL1" : "=r" (sctlr));
	con_hex("EL      ", el);
	con_hex("SCTLR   ", sctlr);

	/* A recovery boot describes the TWRP ramdisk in /chosen. If a Linux
	 * Image is staged in preas, take that branch; otherwise this returns
	 * immediately and the XNU path below is unchanged. */
	pra_linux_try(dtb);

	uintptr_t payload_pa = (uintptr_t)__payload_start;
	uint64_t length;
	if (pra_payload_size != 0x5041594c4f4144ULL &&
	    pra_payload_size >= sizeof(struct payload)) {
		length = pra_payload_size;
		con_puts("length from build\n");
	} else if (dtb > payload_pa) {
		length = (uint64_t)(dtb - payload_pa);
		con_puts("length from dtb\n");
	} else {
		length = 0;
	}
	con_hex("dtb     ", dtb);
	con_hex("payload ", payload_pa);
	con_dec("length  ", length);
	if (length < sizeof(struct payload)) {
		con_puts("FAIL: no payload\n");
		halt();
	}

	const struct payload *p = (const struct payload *)payload_pa;
	if (!magic_ok(p->magic) || p->version != 1 || !p->nsegs || p->nsegs > 32 ||
	    __builtin_offsetof(struct payload, segs) +
	        (uint64_t)p->nsegs * sizeof(struct payload_seg) > length ||
	    p->adt_off > length || p->adt_size > length - p->adt_off) {
		con_puts("FAIL: payload header\n");
		halt();
	}
	con_dec("nsegs   ", p->nsegs);

	if (p->phys_base < RAM_BASE || p->phys_base >= RAM_END ||
	    !p->mem_size || p->mem_size > RAM_END - p->phys_base ||
	    p->entry_va < p->virt_base || p->kernel_end < p->virt_base) {
		con_puts("FAIL: window\n");
		halt();
	}

	uintptr_t memory_end = p->phys_base + p->mem_size;
	uintptr_t kernel_end = p->phys_base + (p->kernel_end - p->virt_base);
	if (kernel_end >= memory_end) {
		con_puts("FAIL: kernel_end\n");
		halt();
	}

	con_hex("virt    ", p->virt_base);
	con_hex("phys    ", p->phys_base);
	con_hex("mem     ", p->mem_size);

	for (uint32_t i = 0; i < p->nsegs; ++i) {
		const struct payload_seg *s = &p->segs[i];
		if (s->vmaddr < p->virt_base || s->file_size > s->vmsize ||
		    s->file_off > length || s->file_size > length - s->file_off ||
		    s->vmsize > p->mem_size ||
		    s->vmaddr - p->virt_base > p->mem_size - s->vmsize) {
			con_puts("FAIL: segment bounds\n");
			halt();
		}
		uintptr_t dst = p->phys_base + (s->vmaddr - p->virt_base);
		copy_bytes(dst, payload_pa + s->file_off, s->file_size);
		zero_bytes(dst + s->file_size, s->vmsize - s->file_size);
		clean_bytes(dst, dst + s->vmsize);
	}

	uintptr_t adt_pa = kernel_end;
	uintptr_t ba_pa = align_page(adt_pa + p->adt_size);
	if (ba_pa + PAGE_SIZE > memory_end || ba_pa < adt_pa) {
		con_puts("FAIL: adt/boot_args placement\n");
		halt();
	}
	copy_bytes(adt_pa, payload_pa + p->adt_off, p->adt_size);
	zero_bytes(ba_pa, PAGE_SIZE);

	volatile struct boot_args *ba = (volatile struct boot_args *)ba_pa;
	ba->Revision = 2;
	ba->Version = 2;
	ba->virtBase = p->virt_base;
	ba->physBase = p->phys_base;
	ba->memSize = p->mem_size;
	ba->topOfKernelData = ba_pa + PAGE_SIZE;
	ba->deviceTreeP = p->virt_base + (adt_pa - p->phys_base);
	ba->deviceTreeLength = (uint32_t)p->adt_size;
	/* pe_init.c walks the progress bar in from the display edge and asserts
	 * *delta >= 0 (pe_init.c:314). With this struct zeroed that loop saw
	 * display_size 0 and ran delta negative on the first step: the 0153
	 * boot panicked in pe_init before launchd. Describe the same scanout
	 * the splash uses; v_depth = depth 32, rotate 0, scale bits 0 (1x).
	 * v_display selects kPEGraphicsMode, which the vc progress bar needs. */
	ba->Video.v_baseAddr = FB_BASE;
	ba->Video.v_display = 1;
	ba->Video.v_rowBytes = FB_STRIDE_PX * 4;
	ba->Video.v_width = FB_WIDTH;
	ba->Video.v_height = FB_HEIGHT;
	ba->Video.v_depth = 32;
	for (unsigned i = 0; i < BOOT_LINE_LENGTH; ++i)
		ba->CommandLine[i] = p->cmdline[i];
	ba->memSizeActual = p->mem_size;
	clean_bytes(adt_pa, ba_pa + PAGE_SIZE);

	uintptr_t entry_pa = p->phys_base + (p->entry_va - p->virt_base);
	if (entry_pa >= kernel_end) {
		con_puts("FAIL: entry\n");
		halt();
	}

	con_hex("adt     ", adt_pa);
	con_hex("ba      ", ba_pa);
	con_hex("entry   ", entry_pa);
	con_puts("jumping to XNU\n");

	__asm__ volatile("ic iallu; dsb sy; isb" : : : "memory");
	pra_jump_mmu_off(entry_pa, ba_pa);
}

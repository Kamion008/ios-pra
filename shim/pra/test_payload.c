/* SPDX-License-Identifier: GPL-2.0-only
 * XNU handoff test payload for the PRA loader.
 *
 * Entered with x0 = boot_args physical address, MMU off, at 0x88000000.
 * It paints the bottom of the splash buffer green (proves the jump) and
 * draws two rows of 32 bars, one per bit, for boot_args->physBase and
 * ->memSize (white = 1, black = 0), so a photo verifies the loader passed
 * the values the ADT asked for: physBase 0x88000000 (bits 31, 27) and
 * memSize 0x20000000 (bit 29).
 *
 * No globals, so the payload has no .bss and needs no zeroing beyond the
 * loader's segment handling.
 */
#include <stdint.h>

#define FB_BASE      0x5D000000UL
#define FB_STRIDE_PX 1080u
#define FB_WIDTH     1080u

struct boot_args_min {
	uint16_t Revision, Version;
	uint64_t virtBase, physBase, memSize, topOfKernelData;
};

static void bars(volatile uint32_t *fb, unsigned row0, unsigned row1,
                 uint64_t value)
{
	for (unsigned b = 0; b < 32; b++) {
		uint32_t color = ((value >> b) & 1) ? 0x00FFFFFFu : 0x00000000u;
		unsigned x0 = b * 33;
		for (unsigned y = row0; y < row1; y++)
			for (unsigned x = x0; x < x0 + 30; x++)
				fb[y * FB_STRIDE_PX + x] = color;
	}
}

void test_entry(uint64_t boot_args_pa)
{
	volatile struct boot_args_min *ba =
		(volatile struct boot_args_min *)(uintptr_t)boot_args_pa;
	volatile uint32_t *fb = (volatile uint32_t *)FB_BASE;

	/* Green band at the bottom: reached the payload. */
	for (unsigned y = 1850; y < 1920; y++)
		for (unsigned x = 0; x < FB_WIDTH; x++)
			fb[y * FB_STRIDE_PX + x] = 0x0000FF00u;

	/* physBase in the upper row, memSize in the lower row. */
	bars(fb, 1550, 1699, ba->physBase);
	bars(fb, 1700, 1849, ba->memSize);

	for (;;)
		__asm__ volatile("wfe");
}

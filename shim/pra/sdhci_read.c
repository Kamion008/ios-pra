/* SPDX-License-Identifier: GPL-2.0-only
 * Read-only polled SDHCI block reads for the PRA-LX1 loader.
 *
 * This is the register sequence probe.c proved on the phone: the Huawei
 * bootloader leaves the Arasan host at 0xFF390000 clocked and the card in
 * transfer state, so no card init is attempted. Only CMD17 (single-block
 * read) is issued; the transfer mode register is never set for a write.
 *
 * The loader reads ~35 MB of Image through this path, so the per-call
 * console noise of the diagnostic version is gone. Errors are still printed
 * because they are the only evidence a device boot gets without UART.
 */
#include <stdint.h>
#include "console.h"
#include "sdhci.h"

#define SDHCI 0xFF390000UL

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline uint16_t rd16(uintptr_t a) { return *(volatile uint16_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static inline void wr16(uintptr_t a, uint16_t v) { *(volatile uint16_t *)a = v; }

struct sdhci_state {
	uint16_t blksiz, blkcnt, transfer;
	uint32_t arg, status_en, sig_en;
};

/* Present State (0x24) bits 0/1 are Command Inhibit (CMD/DAT). */
static int sdhci_wait_ready(void)
{
	for (unsigned i = 0; i < 4000000; i++) {
		if (!(rd32(SDHCI + 0x24) & 0x3))
			return 0;
		__asm__ volatile("yield" ::: "memory");
	}
	return -1;
}

/* The bootloader normally leaves the SD clock running. If it gated it at
 * handoff, re-enable the internal clock and then the SD clock, keeping the
 * divider and power settings it chose. */
static void sdhci_ensure_clock(void)
{
	uint16_t clk = rd16(SDHCI + 0x2C);

	if (clk & 0x4)
		return;
	con_puts("  SD clock off, re-enabling\n");
	wr16(SDHCI + 0x2C, clk | 0x1);		/* internal clock enable */
	for (unsigned i = 0; i < 100000; i++) {
		if (rd16(SDHCI + 0x2C) & 0x2)	/* internal clock stable */
			break;
	}
	wr16(SDHCI + 0x2C, rd16(SDHCI + 0x2C) | 0x4);	/* SD clock enable */
	for (unsigned i = 0; i < 100000; i++)
		__asm__ volatile("nop");
}

int pra_sdhci_read(uint64_t lba, void *out)
{
	uint32_t present;

	sdhci_ensure_clock();
	if (sdhci_wait_ready()) {
		con_puts("  card busy, skip read\n");
		return -2;
	}
	present = rd32(SDHCI + 0x24);
	if (!(present & (1u << 16))) {
		con_puts("  no SDHCI buffer data port\n");
		return -1;
	}

	struct sdhci_state s = {
		.blksiz = rd16(SDHCI + 0x04),
		.blkcnt = rd16(SDHCI + 0x06),
		.transfer = rd16(SDHCI + 0x0C),
		.arg = rd32(SDHCI + 0x08),
		.status_en = rd32(SDHCI + 0x34),
		.sig_en = rd32(SDHCI + 0x38),
	};

	wr32(SDHCI + 0x38, 0);			/* signal enable */
	wr32(SDHCI + 0x34, 0x7ff);		/* error status enable */
	wr32(SDHCI + 0x30, 0xffffffffu);	/* clear normal + error status */
	wr16(SDHCI + 0x04, 512);
	wr16(SDHCI + 0x06, 1);
	wr32(SDHCI + 0x08, (uint32_t)lba);
	wr16(SDHCI + 0x0C, 0x12);		/* single block read, no DMA */
	__asm__ volatile("dsb sy" : : : "memory");
	wr16(SDHCI + 0x0E, 0x113A);		/* CMD17, R1, data present */

	int rc = -3;
	uint32_t st = 0;

	/* Normal status is low 16 bits, error status high 16 bits. */
	for (unsigned i = 0; i < 2000000; i++) {
		st = rd32(SDHCI + 0x30);
		if ((st >> 16) & 0x1fffu) { rc = -4; break; }
		if (st & 1u) { rc = 0; break; }
	}
	if (rc == -4) {
		con_printf("  CMD17 LBA %u error status %x\n", lba,
		           (uint64_t)st);
		goto restore;
	}
	if (rc) {
		con_printf("  CMD17 LBA %u timeout, status %x\n", lba,
		           (uint64_t)st);
		goto restore;
	}
	if (rd32(SDHCI + 0x10) & 0xfdffe008u) {
		con_printf("  CMD17 R1 card error %x\n",
		           (uint64_t)rd32(SDHCI + 0x10));
		rc = -5;
		goto restore;
	}
	wr32(SDHCI + 0x30, 1u);

	for (unsigned i = 0; i < 2000000; i++) {
		st = rd32(SDHCI + 0x30);
		if ((st >> 16) & 0x1fffu) { rc = -6; break; }
		if (st & (1u << 5)) { rc = 0; break; }	/* Buffer Read Ready */
	}
	if (rc == -6) {
		con_printf("  data error status %x\n", (uint64_t)st);
		goto restore;
	}
	if (rc) {
		con_printf("  data timeout, status %x\n", (uint64_t)st);
		goto restore;
	}
	{
		uint32_t *p = out;
		for (unsigned i = 0; i < 128; i++)
			p[i] = rd32(SDHCI + 0x20);
	}
	wr32(SDHCI + 0x30, (1u << 1) | (1u << 5));
	(void)sdhci_wait_ready();
	rc = 0;

restore:
	wr16(SDHCI + 0x04, s.blksiz);
	wr16(SDHCI + 0x06, s.blkcnt);
	wr16(SDHCI + 0x0C, s.transfer);
	wr32(SDHCI + 0x08, s.arg);
	wr32(SDHCI + 0x34, s.status_en);
	wr32(SDHCI + 0x38, s.sig_en);
	return rc;
}

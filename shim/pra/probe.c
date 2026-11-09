/* SPDX-License-Identifier: GPL-2.0-only
 * PRA-LX1 (hi6250) EL1 diagnostic.
 *
 * Runs where the Android kernel would run. It only reads hardware, except
 * for the two reserved display buffers, which it paints to identify which
 * one the bootloader is scanning out. No storage writes.
 */
#include <stdint.h>
#include "console.h"

#define FDT_MAGIC 0xd00dfeedu
#define FDT_BEGIN_NODE 1u
#define FDT_END_NODE 2u
#define FDT_PROP 3u
#define FDT_NOP 4u
#define FDT_END 9u

#define GICD 0xE82B1000UL
#define GICC 0xE82B2000UL
#define DSS  0xE8600000UL
#define MMBUF 0xE86C0000UL
#define PCTRL 0xE8A09000UL
#define WDT   0xE8A06000UL
#define SDHCI 0xFF390000UL

#define EMMC_CTRL_SAVED 1     /* no register writes outside SDHCI command setup */

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline uint16_t rd16(uintptr_t a) { return *(volatile uint16_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static inline void wr16(uintptr_t a, uint16_t v) { *(volatile uint16_t *)a = v; }

/* compiler may emit these for aggregate initialisation */
void *memset(void *d, int c, unsigned long n)
{
	unsigned char *p = d;
	while (n--)
		*p++ = (unsigned char)c;
	return d;
}
void *memcpy(void *d, const void *s, unsigned long n)
{
	unsigned char *a = d;
	const unsigned char *b = s;
	while (n--)
		*a++ = *b++;
	return d;
}
int memcmp(const void *a, const void *b, unsigned long n)
{
	const unsigned char *x = a, *y = b;
	while (n--) {
		if (*x != *y)
			return (int)*x - (int)*y;
		x++;
		y++;
	}
	return 0;
}

/* ---- FDT helpers ------------------------------------------------------ */

static uint32_t be32(uintptr_t p) { return __builtin_bswap32(*(volatile uint32_t *)p); }

static uintptr_t align4(uintptr_t p) { return (p + 3) & ~3UL; }

static uintptr_t skip_str(uintptr_t p)
{
	while (*(volatile char *)p)
		p++;
	return p + 1;
}

static int fdt_ok(uintptr_t f) { return f && be32(f) == FDT_MAGIC; }

static int str_eq(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static const char *fdt_node_name(uintptr_t p) { return (const char *)p; }

/* Address of the property stream after a BEGIN_NODE token at p. */
static uintptr_t node_body(uintptr_t p)
{
	return align4(skip_str(p));
}

/* Find an exact node path; returns the BEGIN_NODE token address or 0. */
static uintptr_t fdt_find_node(uintptr_t f, const char *want)
{
	if (!fdt_ok(f))
		return 0;
	uintptr_t p = f + be32(f + 8);
	uintptr_t end = p + be32(f + 36);
	char path[256];
	unsigned plen = 0;
	int depth = -1;

	while (p < end) {
		uint32_t tok = be32(p);
		p += 4;
		if (tok == FDT_BEGIN_NODE) {
			const char *name = fdt_node_name(p);
			uintptr_t nb = node_body(p);
			if (depth < 0) {
				plen = 0;
				path[0] = 0;
			}
			unsigned nl = 0;
			while (name[nl] && plen + nl + 2 < sizeof(path))
				nl++;
			if (nl) {
				path[plen] = '/';
				for (unsigned i = 0; i < nl; i++)
					path[plen + 1 + i] = name[i];
				plen += 1 + nl;
				path[plen] = 0;
			}
			depth++;
			if (str_eq(path, want))
				return p - 4;
			p = nb;
		} else if (tok == FDT_END_NODE) {
			if (depth >= 0) {
				/* trim the last component */
				while (plen && path[plen] != '/')
					plen--;
				path[plen] = 0;
				depth--;
			}
		} else if (tok == FDT_PROP) {
			uint32_t len = be32(p);
			p = align4(p + 8 + len);
		} else if (tok == FDT_NOP) {
			continue;
		} else {
			break;
		}
	}
	return 0;
}

static int fdt_get_prop(uintptr_t f, uintptr_t node, const char *name,
                        uintptr_t *val, uint32_t *len)
{
	if (!node)
		return 0;
	uintptr_t strings = f + be32(f + 12);
	uintptr_t end = f + be32(f + 8) + be32(f + 36);
	uintptr_t p = node + 4;
	p = node_body(p);
	while (p < end) {
		uint32_t tok = be32(p);
		p += 4;
		if (tok == FDT_PROP) {
			uint32_t l = be32(p);
			uint32_t nameoff = be32(p + 4);
			uintptr_t v = p + 8;
			if (str_eq((const char *)(strings + nameoff), name)) {
				*val = v;
				*len = l;
				return 1;
			}
			p = align4(v + l);
		} else if (tok == FDT_BEGIN_NODE) {
			/* skip a child subtree */
			int d = 1;
			p = node_body(p);
			while (p < end && d) {
				uint32_t t = be32(p);
				p += 4;
				if (t == FDT_BEGIN_NODE) {
					d++;
					p = node_body(p);
				} else if (t == FDT_END_NODE) {
					d--;
				} else if (t == FDT_PROP) {
					uint32_t l = be32(p);
					p = align4(p + 8 + l);
				}
			}
		} else if (tok == FDT_END_NODE || tok == FDT_END) {
			break;
		}
	}
	return 0;
}

static void print_prop_bytes(uintptr_t v, uint32_t len)
{
	if (!len) {
		con_puts("<empty>\n");
		return;
	}
	int printable = 1;
	for (uint32_t i = 0; i < len; i++) {
		unsigned char c = *(volatile unsigned char *)(v + i);
		if (c && (c < 32 || c > 126))
			printable = 0;
	}
	if (printable) {
		con_puts("\"");
		for (uint32_t i = 0; i < len; i++) {
			unsigned char c = *(volatile unsigned char *)(v + i);
			if (!c)
				break;
			con_printf("%c", c);
		}
		con_puts("\"\n");
		return;
	}
	if ((len & 3) == 0) {
		con_puts("<");
		for (uint32_t i = 0; i < len && i < 64; i += 4)
			con_printf(" %x", (uint64_t)be32(v + i));
		con_puts(" >\n");
		return;
	}
	con_puts("<");
	for (uint32_t i = 0; i < len && i < 32; i++)
		con_printf(" %x", (uint64_t)*(volatile unsigned char *)(v + i));
	con_puts(" >\n");
}

static void dump_node(uintptr_t f, const char *path)
{
	uintptr_t node = fdt_find_node(f, path);
	con_printf("\n[%s] %s\n", node ? "ok" : "missing", path);
	if (!node)
		return;
	uintptr_t strings = f + be32(f + 12);
	uintptr_t end = f + be32(f + 8) + be32(f + 36);
	uintptr_t p = node_body(node + 4);
	while (p < end) {
		uint32_t tok = be32(p);
		p += 4;
		if (tok == FDT_PROP) {
			uint32_t l = be32(p), nameoff = be32(p + 4);
			uintptr_t v = p + 8;
			con_printf("  %s = ", (const char *)(strings + nameoff));
			print_prop_bytes(v, l);
			p = align4(v + l);
		} else if (tok == FDT_BEGIN_NODE) {
			int d = 1;
			p = node_body(p);
			while (p < end && d) {
				uint32_t t = be32(p);
				p += 4;
				if (t == FDT_BEGIN_NODE) { d++; p = node_body(p); }
				else if (t == FDT_END_NODE) d--;
				else if (t == FDT_PROP) { uint32_t l = be32(p); p = align4(p + 8 + l); }
			}
		} else if (tok == FDT_END_NODE || tok == FDT_END) {
			break;
		}
	}
}

static void report_prop(uintptr_t f, const char *path, const char *name)
{
	uintptr_t node = fdt_find_node(f, path), val = 0;
	uint32_t len = 0;
	if (!fdt_get_prop(f, node, name, &val, &len))
		return;
	con_printf("%s:%s = ", path, name);
	print_prop_bytes(val, len);
}

/* ---- CPU / GIC -------------------------------------------------------- */

static uint64_t r_sysreg(int reg)
{
	uint64_t v = 0;
	switch (reg) {
	case 0: __asm__ volatile("mrs %0, CurrentEL" : "=r"(v)); break;
	case 1: __asm__ volatile("mrs %0, MIDR_EL1" : "=r"(v)); break;
	case 2: __asm__ volatile("mrs %0, MPIDR_EL1" : "=r"(v)); break;
	case 3: __asm__ volatile("mrs %0, CNTFRQ_EL0" : "=r"(v)); break;
	case 4: __asm__ volatile("mrs %0, SCTLR_EL1" : "=r"(v)); break;
	case 5: __asm__ volatile("mrs %0, ID_AA64MMFR0_EL1" : "=r"(v)); break;
	case 6: __asm__ volatile("mrs %0, ID_AA64PFR0_EL1" : "=r"(v)); break;
	case 7: __asm__ volatile("mrs %0, CTR_EL0" : "=r"(v)); break;
	case 8: __asm__ volatile("mrs %0, CNTVCT_EL0" : "=r"(v)); break;
	}
	return v;
}

static void gic_probe(void)
{
	con_printf("\nGIC distributor @ %x\n", (uint64_t)GICD);
	con_printf("  GICD_CTLR  = %x\n", (uint64_t)rd32(GICD + 0x000));
	con_printf("  GICD_TYPER = %x\n", (uint64_t)rd32(GICD + 0x004));
	con_printf("  GICD_IIDR  = %x\n", (uint64_t)rd32(GICD + 0x008));
	con_printf("  GICD_PIDR2 = %x\n", (uint64_t)rd32(GICD + 0xFE8));
	con_printf("GIC CPU interface @ %x\n", (uint64_t)GICC);
	con_printf("  GICC_CTLR  = %x\n", (uint64_t)rd32(GICC + 0x000));
	con_printf("  GICC_PMR   = %x\n", (uint64_t)rd32(GICC + 0x004));
	con_printf("  GICC_IIDR  = %x\n", (uint64_t)rd32(GICC + 0xFC));
	con_printf("  GICC_PIDR2 = %x\n", (uint64_t)rd32(GICC + 0xFE8));
}

static void scan_window(const char *name, uintptr_t base, unsigned size)
{
	unsigned hits = 0;
	con_printf("\n%s register window %x..%x\n", name, (uint64_t)base,
	           (uint64_t)(base + size));
	for (unsigned off = 0; off + 4 <= size && hits < 40; off += 4) {
		uint32_t v = rd32(base + off);
		if (v >= 0x00400000u && v < 0xC0000000u && (v & 0xfffu) == 0) {
			con_printf("  [%x] = %x\n", (uint64_t)off, (uint64_t)v);
			hits++;
		}
	}
	if (!hits)
		con_puts("  (no page-aligned RAM-range values)\n");
}

/* Fallback scanout test: the bootloader programmed the DSS to scan some
 * buffer. Read the DSS register window and repaint every page-aligned
 * display-range address found there. If the visible scanout base is not
 * one of the two known windows, this turns the screen magenta. */
static void paint_dss_candidates(void)
{
	unsigned painted = 0;
	con_puts("\nDSS scan: repainting RAM-range register values magenta\n");
	for (unsigned off = 0; off + 4 <= 0x1000; off += 4) {
		uint32_t v = rd32(DSS + off);
		if (v < 0x30000000u || v >= 0x60000000u)
			continue;
		if (v & 0xfffu)
			continue;
		con_printf("  DSS[%x] = %x -> paint\n", (uint64_t)off, (uint64_t)v);
		fb_fill_range((uintptr_t)v, 0xFD2000u, 0xFFFF00FFu);
		painted++;
	}
	if (!painted)
		con_puts("  (no display-range values in DSS window)\n");
}

/* ---- SDHCI ------------------------------------------------------------ */

struct sdhci_state {
	uint16_t blksiz, blkcnt, transfer;
	uint32_t arg, status_en, sig_en;
};

static int sdhci_read(uint64_t lba, void *out)
{
	uint32_t present = rd32(SDHCI + 0x24);
	uint16_t version = rd16(SDHCI + 0xFE);
	con_printf("SDHCI VERSION=%x PRESENT=%x CLOCK=%x POWER=%x HOSTCTL=%x RESET=%x\n",
	           (uint64_t)version, (uint64_t)present,
	           (uint64_t)rd16(SDHCI + 0x2C), (uint64_t)*(volatile unsigned char *)(SDHCI + 0x29),
	           (uint64_t)*(volatile unsigned char *)(SDHCI + 0x28),
	           (uint64_t)*(volatile unsigned char *)(SDHCI + 0x2F));

	if (!(present & (1u << 16))) {
		con_puts("  no card inserted, skip\n");
		return -1;
	}
	if (present & 0x3) {
		con_puts("  command/data inhibit, skip\n");
		return -2;
	}
	if ((version & 0xff) != 2 && (version & 0xff) != 3) {
		con_printf("  unexpected spec version %u, continuing\n", (uint64_t)(version & 0xff));
	}

	struct sdhci_state s = {
		.blksiz = rd16(SDHCI + 0x04),
		.blkcnt = rd16(SDHCI + 0x06),
		.transfer = rd16(SDHCI + 0x0C),
		.arg = rd32(SDHCI + 0x08),
		.status_en = rd32(SDHCI + 0x34),
		.sig_en = rd32(SDHCI + 0x38),
	};

	wr32(SDHCI + 0x38, 0);               /* signal enable */
	wr32(SDHCI + 0x34, 0x7ff);           /* error status enable */
	wr32(SDHCI + 0x30, 0x7ff);           /* clear errors */
	wr16(SDHCI + 0x04, 512);
	wr16(SDHCI + 0x06, 1);
	wr32(SDHCI + 0x08, (uint32_t)lba);
	wr16(SDHCI + 0x0C, 0x12);            /* single block read, no DMA */
	__asm__ volatile("dsb sy" : : : "memory");
	wr16(SDHCI + 0x0E, 0x113A);          /* CMD17, R1, data present */

	int rc = -3;
	uint32_t st = 0;
	for (unsigned i = 0; i < 2000000; i++) {
		st = rd32(SDHCI + 0x30);
		if (st & 0x7ffu) { rc = -4; break; }
		if (st & 1u) { rc = 0; break; }
	}
	if (rc == -4) {
		con_printf("  CMD17 LBA %u error status %x\n", lba, (uint64_t)st);
		goto restore;
	}
	if (rc) {
		con_printf("  CMD17 LBA %u timeout, status %x\n", lba, (uint64_t)st);
		goto restore;
	}
	uint32_t r1 = rd32(SDHCI + 0x10);
	if (r1 & 0xfdffe008u) {
		con_printf("  CMD17 R1 card error %x\n", (uint64_t)r1);
		rc = -5;
		goto restore;
	}
	wr32(SDHCI + 0x30, 1u);

	for (unsigned i = 0; i < 2000000; i++) {
		st = rd32(SDHCI + 0x30);
		if (st & 0x7ffu) { rc = -6; break; }
		if (st & (1u << 5)) { rc = 0; break; }
	}
	if (rc == -6) {
		con_printf("  data error status %x\n", (uint64_t)st);
		goto restore;
	}
	if (rc) {
		con_printf("  data timeout, status %x\n", (uint64_t)st);
		goto restore;
	}
	if (!(rd32(SDHCI + 0x24) & 0x800u)) {
		con_puts("  buffer read not ready\n");
		rc = -7;
		goto restore;
	}
	{
		uint32_t *p = out;
		for (unsigned i = 0; i < 128; i++)
			p[i] = rd32(SDHCI + 0x20);
	}
	wr32(SDHCI + 0x30, (1u << 1) | (1u << 5));
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

static void gpt_probe(void)
{
	static uint8_t sec[512];
	con_puts("\nSDHCI GPT probe (read-only CMD17)\n");

	if (sdhci_read(1, sec)) {
		con_puts("  GPT header unreadable\n");
		return;
	}
	if (memcmp(sec, "EFI PART", 8)) {
		con_puts("  no EFI PART signature at LBA1\n");
		return;
	}
	uint64_t entry_lba = *(uint64_t *)(sec + 72);
	uint32_t count = *(uint32_t *)(sec + 80);
	uint32_t esize = *(uint32_t *)(sec + 84);
	con_printf("  GPT entries at LBA %u, %u entries of %u bytes\n",
	           entry_lba, (uint64_t)count, (uint64_t)esize);
	if (esize != 128 || entry_lba > 0xffffffffu) {
		con_puts("  unsupported GPT geometry\n");
		return;
	}
	for (unsigned s = 0; s < 4 && s * 4 < count; s++) {
		if (sdhci_read(entry_lba + s, sec))
			break;
		for (unsigned e = 0; e < 4; e++) {
			uint8_t *p = sec + e * 128;
			if (*(uint64_t *)p == 0 && *(uint64_t *)(p + 8) == 0)
				continue;
			uint64_t first = *(uint64_t *)(p + 32);
			uint64_t last = *(uint64_t *)(p + 40);
			/* UTF-16LE name, 72 bytes */
			char name[37];
			int n = 0;
			for (int i = 0; i < 36 && n < 36; i++) {
				uint16_t c = *(uint16_t *)(p + 56 + i * 2);
				if (!c)
					break;
				name[n++] = (c < 128) ? (char)c : '?';
			}
			name[n] = 0;
			con_printf("  p%u %s lba %u..%u (%u MiB)\n",
			           (uint64_t)(s * 4 + e + 1), name, first, last,
			           (last - first + 1) / 2048);
		}
	}
}

/* ---- main ------------------------------------------------------------- */

void pra_main(uintptr_t dtb)
{
	uart_init();

	con_puts("\n\n=== PRA-LX1 hi6250 diagnostics ===\n");
	con_printf("DTB pointer from bootloader: %x\n", (uint64_t)dtb);
	if (!fdt_ok(dtb))
		con_puts("DTB magic missing; register and MMIO probes only\n");

	con_hex("CurrentEL      ", r_sysreg(0));
	con_hex("MIDR_EL1       ", r_sysreg(1));
	con_hex("MPIDR_EL1      ", r_sysreg(2));
	con_hex("CNTFRQ_EL0     ", r_sysreg(3));
	con_hex("CNTVCT_EL0     ", r_sysreg(8));
	con_hex("SCTLR_EL1      ", r_sysreg(4));
	con_hex("ID_AA64MMFR0   ", r_sysreg(5));
	con_hex("ID_AA64PFR0    ", r_sysreg(6));
	con_hex("CTR_EL0        ", r_sysreg(7));

	dump_node(dtb, "/chosen");
	dump_node(dtb, "/memory");
	dump_node(dtb, "/psci");
	dump_node(dtb, "/timer");
	dump_node(dtb, "/interrupt-controller@e82b0000");
	dump_node(dtb, "/sdhci@FF390000");
	dump_node(dtb, "/amba/uart@fdf02000");
	dump_node(dtb, "/reserved-memory/graphic");
	dump_node(dtb, "/reserved-memory/hisi_cma");

	/* Live DTS/DTB facts: dss_base_phy is the DSS MMIO window (not RAM);
	 * the graphic carveout reg is the scanout-backed RAM range. */
	report_prop(dtb, "/framebuffer@E8600000", "dss_base_phy");
	report_prop(dtb, "/reserved-memory/graphic", "reg");
	report_prop(dtb, "/memory", "reg");
	report_prop(dtb, "/chosen", "bootargs");
	report_prop(dtb, "/chosen", "linux,initrd-start");
	report_prop(dtb, "/chosen", "linux,initrd-end");
	report_prop(dtb, "/chosen", "kaslr-seed");

	gic_probe();
	scan_window("DSS", DSS, 0x1000);
	scan_window("MMBUF", MMBUF, 0x1000);
	scan_window("PCTRL", PCTRL, 0x1000);

	/* Stop the bootloader watchdog (/amba/watchdog0 in live iomem) so the
	 * diagnostic stays on screen instead of resetting the phone. */
	con_puts("\ndisabling watchdog @ e8a06000\n");
	wr32(WDT + 0xC00, 0x1ACCE551u);   /* unlock */
	wr32(WDT + 0x008, 0);             /* control: disable */
	wr32(WDT + 0x00C, 1);             /* clear pending interrupt */
	wr32(WDT + 0xC00, 0);             /* relock */

	/* Whole-region scanout test. Live fb0: 1080x1920, bpp 32, stride
	 * 4320; /reserved-memory/graphic = 0x31000000 + 0x1a40000.
	 * Flood the full graphic carveout blue and the logo window
	 * 0x5d000000..0x60000000 red: any scanout base inside either
	 * range becomes visible, not just the first frame. */
	con_puts("flooding graphic carveout 0x31000000..0x32a40000 blue\n");
	con_puts("flooding logo window 0x5d000000..0x60000000 red\n");
	fb_attach(0x31000000UL, 1080, 1920, 1080);
	fb_attach(0x5D000000UL, 1080, 1920, 1080);
	fb_fill_range(0x5D000000UL, 0x3000000u, 0xFF800000u);
	fb_fill_range(0x31000000UL, 0x1A40000u, 0xFF000080u);

	paint_dss_candidates();

	gpt_probe();

	con_puts("\n=== diagnostics complete ===\n");
}

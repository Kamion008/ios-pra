/* SPDX-License-Identifier: GPL-2.0-only
 * PRA-LX1 (hi6250) EL1 diagnostic.
 *
 * Runs where the Android kernel would run. It reads hardware, paints the
 * candidate display buffers, persists the DSS/MMBUF/PCTRL register windows
 * to a scratch area in erecovery_kernel, then sets misc=boot-recovery and
 * resets into TWRP so the dump can be read over ADB.
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

/* ---- Persistent diagnostic dump --------------------------------------- *
 * The screen is the only external output and the DSS scanout base is the
 * unknown. Persist the register windows to a scratch area the bootloader
 * does not touch during a recovery boot (16 MiB into erecovery_kernel),
 * then set the BCB and reset into TWRP so the dump can be read over ADB.
 */

#define MISC_LBA    507904ULL          /* live GPT: misc first_lba */
#define P27_LBA     753664ULL          /* live GPT: erecovery_kernel first_lba */
#define DUMP_LBA    (P27_LBA + 0x8000ULL) /* +16 MiB, past the 11 MiB image */

struct pra_dump {
	uint8_t  magic[8];             /* "PRADMP01" */
	uint32_t version;
	uint32_t ncand;
	uint64_t cel, midr, mpidr, cntfrq, sctlr, mmfr0, pfr0, ctr;
	struct { uint32_t win, off, val; } cand[32];
	uint32_t dss[1024];
	uint32_t mmbuf[1024];
	uint32_t pctrl[1024];
	uint8_t  pad[48];
};

static void add_cands(struct pra_dump *d, uint32_t win, uintptr_t base)
{
	for (unsigned off = 0; off + 4 <= 0x1000 && d->ncand < 32; off += 4) {
		uint32_t v = rd32(base + off);
		if (v < 0x30000000u || v >= 0xE0000000u || (v & 0xfffu))
			continue;
		d->cand[d->ncand].win = win;
		d->cand[d->ncand].off = off;
		d->cand[d->ncand].val = v;
		d->ncand++;
	}
}

static void build_dump(struct pra_dump *d)
{
	memset(d, 0, sizeof(*d));
	memcpy(d->magic, "PRADMP01", 8);
	d->version = 1;
	d->cel = r_sysreg(0);
	d->midr = r_sysreg(1);
	d->mpidr = r_sysreg(2);
	d->cntfrq = r_sysreg(3);
	d->sctlr = r_sysreg(4);
	d->mmfr0 = r_sysreg(5);
	d->pfr0 = r_sysreg(6);
	d->ctr = r_sysreg(7);
	add_cands(d, 0, DSS);
	add_cands(d, 1, MMBUF);
	add_cands(d, 2, PCTRL);
	for (unsigned i = 0; i < 1024; i++) {
		d->dss[i] = rd32(DSS + i * 4);
		d->mmbuf[i] = rd32(MMBUF + i * 4);
		d->pctrl[i] = rd32(PCTRL + i * 4);
	}
}

static void delay_seconds(unsigned s)
{
	uint64_t freq = r_sysreg(3);
	uint64_t start, now;
	if (!freq)
		freq = 1920000;
	__asm__ volatile("mrs %0, CNTPCT_EL0" : "=r"(start));
	do {
		__asm__ volatile("mrs %0, CNTPCT_EL0" : "=r"(now));
	} while ((now - start) < freq * (uint64_t)s);
}

/* PSCI v0.1 on hi6250 uses the SMC conduit. */
static void psci_system_reset(void)
{
	register uint64_t x0 __asm__("x0") = 0x84000009ULL;
	register uint64_t x1 __asm__("x1") = 0;
	register uint64_t x2 __asm__("x2") = 0;
	register uint64_t x3 __asm__("x3") = 0;
	__asm__ volatile("smc #0" : "+r"(x0)
	                 : "r"(x1), "r"(x2), "r"(x3) : "memory");
	for (;;)
		__asm__ volatile("wfe");
}

/* ---- SDHCI ------------------------------------------------------------ */

static int sdhci_write(uint64_t lba, const void *in);

struct sdhci_state {
	uint16_t blksiz, blkcnt, transfer;
	uint32_t arg, status_en, sig_en;
};

/* Present State (0x24) bits 0/1 are Command Inhibit (CMD/DAT). The card can
 * stay busy for a while after a write, so poll instead of failing. */
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
	con_printf("  SD clock off (%x), re-enabling\n", (uint64_t)clk);
	wr16(SDHCI + 0x2C, clk | 0x1);       /* internal clock enable */
	for (unsigned i = 0; i < 100000; i++) {
		if (rd16(SDHCI + 0x2C) & 0x2) /* internal clock stable */
			break;
	}
	wr16(SDHCI + 0x2C, rd16(SDHCI + 0x2C) | 0x4); /* SD clock enable */
	for (unsigned i = 0; i < 100000; i++)
		__asm__ volatile("nop");
}

static int sdhci_read(uint64_t lba, void *out)
{
	uint32_t present = rd32(SDHCI + 0x24);
	uint16_t version = rd16(SDHCI + 0xFE);
	con_printf("SDHCI VERSION=%x PRESENT=%x CLOCK=%x POWER=%x HOSTCTL=%x RESET=%x\n",
	           (uint64_t)version, (uint64_t)present,
	           (uint64_t)rd16(SDHCI + 0x2C), (uint64_t)*(volatile unsigned char *)(SDHCI + 0x29),
	           (uint64_t)*(volatile unsigned char *)(SDHCI + 0x28),
	           (uint64_t)*(volatile unsigned char *)(SDHCI + 0x2F));

	if ((version & 0xff) != 2 && (version & 0xff) != 3) {
		con_printf("  unexpected spec version %u, continuing\n", (uint64_t)(version & 0xff));
	}
	sdhci_ensure_clock();
	if (sdhci_wait_ready()) {
		con_puts("  card busy, skip read\n");
		return -2;
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
	wr32(SDHCI + 0x30, 0xffffffffu);     /* clear normal + error status */
	wr16(SDHCI + 0x04, 512);
	wr16(SDHCI + 0x06, 1);
	wr32(SDHCI + 0x08, (uint32_t)lba);
	wr16(SDHCI + 0x0C, 0x12);            /* single block read, no DMA */
	__asm__ volatile("dsb sy" : : : "memory");
	wr16(SDHCI + 0x0E, 0x113A);          /* CMD17, R1, data present */

	int rc = -3;
	uint32_t st = 0;
	/* Normal status is low 16 bits, error status high 16 bits. */
	for (unsigned i = 0; i < 2000000; i++) {
		st = rd32(SDHCI + 0x30);
		if ((st >> 16) & 0x1fffu) { rc = -4; break; }
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
		if ((st >> 16) & 0x1fffu) { rc = -6; break; }
		if (st & (1u << 5)) { rc = 0; break; }  /* Buffer Read Ready */
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

static int
sdhci_write(uint64_t lba, const void *in)
{
	sdhci_ensure_clock();
	if (sdhci_wait_ready()) {
		con_puts("  card busy, skip write\n");
		return -2;
	}

	struct sdhci_state s = {
		.blksiz = rd16(SDHCI + 0x04),
		.blkcnt = rd16(SDHCI + 0x06),
		.transfer = rd16(SDHCI + 0x0C),
		.arg = rd32(SDHCI + 0x08),
		.status_en = rd32(SDHCI + 0x34),
		.sig_en = rd32(SDHCI + 0x38),
	};

	wr32(SDHCI + 0x38, 0);
	wr32(SDHCI + 0x34, 0x7ff);
	wr32(SDHCI + 0x30, 0xffffffffu);   /* clear normal + error status */
	wr16(SDHCI + 0x04, 512);
	wr16(SDHCI + 0x06, 1);
	wr32(SDHCI + 0x08, (uint32_t)lba);
	wr16(SDHCI + 0x0C, 0x02);          /* single block, write, no DMA */
	__asm__ volatile("dsb sy" : : : "memory");
	wr16(SDHCI + 0x0E, 0x183A);        /* CMD24, R1, data present */

	int rc = -3;
	uint32_t st = 0;

	/* Normal interrupt status is the low 16 bits, error status the high 16. */
	for (unsigned i = 0; i < 2000000; i++) {
		st = rd32(SDHCI + 0x30);
		if ((st >> 16) & 0x1fffu) { rc = -4; break; }
		if (st & 1u) { rc = 0; break; }
	}
	if (rc == -4) {
		con_printf("  CMD24 LBA %u error status %x\n", lba, (uint64_t)st);
		goto restore;
	}
	if (rc) {
		con_printf("  CMD24 LBA %u timeout, status %x\n", lba, (uint64_t)st);
		goto restore;
	}
	if (rd32(SDHCI + 0x10) & 0xfdffe008u) {
		con_printf("  CMD24 R1 card error %x\n", (uint64_t)rd32(SDHCI + 0x10));
		rc = -5;
		goto restore;
	}
	wr32(SDHCI + 0x30, 1u);            /* clear command complete */

	for (unsigned i = 0; i < 2000000; i++) {
		st = rd32(SDHCI + 0x30);
		if ((st >> 16) & 0x1fffu) { rc = -6; break; }
		if (st & (1u << 4)) { rc = 0; break; }  /* Buffer Write Ready */
	}
	if (rc) {
		con_printf("  buffer write not ready, status %x\n", (uint64_t)st);
		goto restore;
	}

	{
		const uint32_t *p = in;
		for (unsigned i = 0; i < 128; i++)
			wr32(SDHCI + 0x20, p[i]);
	}

	for (unsigned i = 0; i < 2000000; i++) {
		st = rd32(SDHCI + 0x30);
		if ((st >> 16) & 0x1fffu) { rc = -7; break; }
		if (st & (1u << 1)) { rc = 0; break; }  /* Transfer Complete */
	}
	if (rc) {
		con_printf("  write transfer not complete, status %x\n", (uint64_t)st);
		goto restore;
	}
	wr32(SDHCI + 0x30, (1u << 1) | (1u << 4));
	(void)sdhci_wait_ready();          /* let the card finish programming */
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

	/* Paint first, before any probe that could fault. If the shim runs at
	 * all, one of these ranges is on screen. The logo buffer is red, the
	 * kernel graphic carveout is blue. No console attach: plain stores. */
	fb_fill_range(0x5D000000UL, 0x3000000u, 0xFF800000u);
	fb_fill_range(0x31000000UL, 0x1A40000u, 0xFF000080u);

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

	/* The early flood above already painted both candidate ranges. Now
	 * repaint any page-aligned display-range value found in the DSS
	 * registers, in case the scanout base is a third address. */
	paint_dss_candidates();

	gpt_probe();

	con_puts("\n=== diagnostics complete ===\n");

	/* Set the BCB first and verify it with a read-back. If the write path
	 * is broken, halt instead of resetting into an endless shim loop. */
	static uint8_t bcb[512];
	memset(bcb, 0, sizeof(bcb));
	memcpy(bcb, "boot-recovery", 13);
	con_puts("writing misc=boot-recovery\n");
	if (sdhci_write(MISC_LBA, bcb)) {
		con_puts("misc write FAILED; halting\n");
		for (;;)
			__asm__ volatile("wfe");
	}

	static uint8_t verify[512];
	if (sdhci_read(MISC_LBA, verify) || memcmp(verify, bcb, 512)) {
		con_puts("misc read-back mismatch; halting\n");
		for (;;)
			__asm__ volatile("wfe");
	}
	con_puts("misc verified\n");

	/* Persist the register windows, then make the bootloader return us to
	 * TWRP automatically. The dump goes past the stock kernel image in
	 * erecovery_kernel, which a recovery boot never reads. */
	static struct pra_dump dump;
	build_dump(&dump);
	con_puts("writing dump to erecovery_kernel +16 MiB\n");
	int ok = 0;
	for (unsigned i = 0; i < sizeof(dump) / 512; i++) {
		if (sdhci_write(DUMP_LBA + i, (const uint8_t *)&dump + i * 512))
			ok = -1;
	}
	con_printf("dump write %s (%u bytes)\n", ok ? "FAILED" : "ok",
	           (uint64_t)sizeof(dump));

	con_puts("resetting to TWRP in 10 s\n");
	delay_seconds(10);
	psci_system_reset();
}

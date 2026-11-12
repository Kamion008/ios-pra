/* SPDX-License-Identifier: GPL-2.0-only
 * PRA-LX1 (hi6250 / Kirin 655) dual-boot branch: boot a staged Linux Image
 * only on a recovery boot.
 *
 * The Huawei bootloader takes the kernel from `kernel` (p30) and, for a
 * recovery boot, only the ramdisk from `recovery_ramdisk` (p32). It then
 * describes that ramdisk in the live DTB, and a card-attached recovery boot
 * measured on the phone reports:
 *
 *   /chosen/linux,initrd-start = 0x08000000
 *   /chosen/linux,initrd-end   = 0x0c9c9d00   (~76.8 MB, p32 ramdisk area)
 *
 * Those properties do not say "recovery" by themselves: an ordinary boot
 * attaches the Android ramdisk the same way, so branching on the initrd
 * alone sent plain power-ons down this path. What does distinguish the two
 * is /chosen/bootargs, which the bootloader builds per boot:
 *
 *   recovery  enter_recovery=1 enter_erecovery=0 ... recovery_update=1
 *             androidboot.mode=normal   normal_reset_type=VolUsbUpdate
 *   normal    enter_recovery=0   (expected, not read from a normal-boot DTB)
 *
 * androidboot.mode is `normal` in both, so it cannot be the trigger.
 *
 * `enter_recovery=1` is not a trigger either: LK's eRecovery failsafe sets
 * it itself on every power-on while it stays latched (that is how it loads
 * p27 and the p28 ramdisk), so branching on it booted the staged Image on an
 * ordinary power-on. This branch now requires the exact space-delimited
 * token `pra_linux=1`, which nothing in the boot chain sets today. It is an
 * explicit opt-in for a future dual-boot trigger (misc flag, key state read
 * by the loader, ...); until then the branch is inert and fails closed to
 * XNU, and a plain power-on can never take the staged Image even when its
 * header and CRC are valid.
 *
 * The Image itself is staged in `preas` (p51) by
 * tools/pra-stage-twrp-kernel.sh. The header and CRC let a blank partition
 * (or a torn write) decline cleanly, in which case boot_main.c continues
 * with XNU exactly as it did before.
 */
#include <stdint.h>
#include "console.h"
#include "linux_boot.h"
#include "sdhci.h"

#define FDT_MAGIC	0xd00dfeedu
#define FDT_BEGIN_NODE	1u
#define FDT_END_NODE	2u
#define FDT_PROP	3u
#define FDT_NOP		4u
#define FDT_END		9u

/* arm64 Image header: "ARM\x64" at byte 56, little-endian fields. */
#define LINUX_IMAGE_MAGIC	0x644d5241u
#define LINUX_TEXT_ALIGN	(2ULL * 1024 * 1024)
#define LINUX_INTERNAL_MAX	(256ULL * 1024 * 1024)

/* The bootloader watchdog is still running when this loader executes. A
 * ~35 MB read through the polled path takes far longer than the diagnostic
 * shim's short run, so stop it first, as probe.c does. This is an MMIO write
 * to the watchdog, not storage. */
#define WDT 0xE8A06000UL

extern void pra_jump_linux(uintptr_t dtb, uintptr_t entry)
	__attribute__((noreturn));

/* ---- FDT helpers (same walk as probe.c, read-only) -------------------- */

static uint32_t fdt_be32(uintptr_t p)
{
	const volatile uint8_t *b = (const volatile uint8_t *)p;

	return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) |
	       ((uint32_t)b[2] << 8) | (uint32_t)b[3];
}

static uintptr_t fdt_align4(uintptr_t p) { return (p + 3) & ~3UL; }

static uintptr_t fdt_skip_str(uintptr_t p)
{
	while (*(volatile char *)p)
		p++;
	return p + 1;
}

static int fdt_ok(uintptr_t f)
{
	return f && fdt_be32(f) == FDT_MAGIC && fdt_be32(f + 4) != 0;
}

static int fdt_str_eq(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static uintptr_t fdt_node_body(uintptr_t p)
{
	return fdt_align4(fdt_skip_str(p));
}

/* Find an exact node path; returns the BEGIN_NODE token address or 0. */
static uintptr_t fdt_find_node(uintptr_t f, const char *want)
{
	if (!fdt_ok(f))
		return 0;
	uintptr_t p = f + fdt_be32(f + 8);
	uintptr_t end = p + fdt_be32(f + 36);
	char path[128];
	unsigned plen = 0;
	int depth = -1;

	while (p < end) {
		uint32_t tok = fdt_be32(p);

		p += 4;
		if (tok == FDT_BEGIN_NODE) {
			const char *name = (const char *)p;
			uintptr_t nb = fdt_node_body(p);

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
			if (fdt_str_eq(path, want))
				return p - 4;
			p = nb;
		} else if (tok == FDT_END_NODE) {
			if (depth >= 0) {
				while (plen && path[plen] != '/')
					plen--;
				path[plen] = 0;
				depth--;
			}
		} else if (tok == FDT_PROP) {
			uint32_t len = fdt_be32(p);

			p = fdt_align4(p + 8 + len);
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
	uintptr_t strings = f + fdt_be32(f + 12);
	uintptr_t end = f + fdt_be32(f + 8) + fdt_be32(f + 36);
	uintptr_t p = fdt_node_body(node + 4);

	while (p < end) {
		uint32_t tok = fdt_be32(p);

		p += 4;
		if (tok == FDT_PROP) {
			uint32_t l = fdt_be32(p);
			uint32_t nameoff = fdt_be32(p + 4);
			uintptr_t v = p + 8;

			if (fdt_str_eq((const char *)(strings + nameoff), name)) {
				*val = v;
				*len = l;
				return 1;
			}
			p = fdt_align4(v + l);
		} else if (tok == FDT_BEGIN_NODE) {
			int d = 1;

			p = fdt_node_body(p);
			while (p < end && d) {
				uint32_t t = fdt_be32(p);

				p += 4;
				if (t == FDT_BEGIN_NODE) {
					d++;
					p = fdt_node_body(p);
				} else if (t == FDT_END_NODE) {
					d--;
				} else if (t == FDT_PROP) {
					uint32_t l = fdt_be32(p);

					p = fdt_align4(p + 8 + l);
				}
			}
		} else if (tok == FDT_END_NODE || tok == FDT_END) {
			break;
		}
	}
	return 0;
}

/* /chosen initrd properties are one or two cells. */
static int fdt_prop_u64(uintptr_t p, uint32_t len, uint64_t *out)
{
	if (len == 4) {
		*out = fdt_be32(p);
		return 1;
	}
	if (len == 8) {
		*out = ((uint64_t)fdt_be32(p) << 32) | fdt_be32(p + 4);
		return 1;
	}
	return 0;
}

/* Returns 1 only for a usable recovery initrd in the first RAM bank. */
static int initrd_range(uintptr_t dtb, uintptr_t *start, uintptr_t *end)
{
	uintptr_t node, val;
	uint32_t len;
	uint64_t s, e;

	if (!fdt_ok(dtb))
		return 0;
	node = fdt_find_node(dtb, "/chosen");
	if (!node)
		return 0;
	if (!fdt_get_prop(dtb, node, "linux,initrd-start", &val, &len) ||
	    !fdt_prop_u64(val, len, &s))
		return 0;
	if (!fdt_get_prop(dtb, node, "linux,initrd-end", &val, &len) ||
	    !fdt_prop_u64(val, len, &e))
		return 0;
	if (!s || e <= s || e > PRA_LINUX_RAM_END)
		return 0;
	*start = (uintptr_t)s;
	*end = (uintptr_t)e;
	return 1;
}

/* True when /chosen/bootargs carries `token` as a whole space-delimited
 * token. A missing bootargs property, or a string with no such token, is
 * simply false; nothing is assumed about the rest of the line. */
static int bootarg_has(uintptr_t dtb, const char *token)
{
	uintptr_t node, val;
	uint32_t len, tlen = 0;

	while (token[tlen])
		tlen++;
	if (!fdt_ok(dtb))
		return 0;
	node = fdt_find_node(dtb, "/chosen");
	if (!node)
		return 0;
	if (!fdt_get_prop(dtb, node, "bootargs", &val, &len))
		return 0;
	for (uint32_t i = 0; i + tlen <= len; i++) {
		const char *p = (const char *)(val + i);
		uint32_t j = 0;

		if (i > 0 && p[-1] != ' ')
			continue;
		while (j < tlen && p[j] == token[j])
			j++;
		if (j != tlen)
			continue;
		if (i + tlen == len || p[tlen] == ' ' || p[tlen] == '\0')
			return 1;
	}
	return 0;
}

/* ---- arm64 Image and staging header validation ------------------------ */

static uint32_t le32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
	       ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t le64(const uint8_t *p)
{
	return (uint64_t)le32(p) | ((uint64_t)le32(p + 4) << 32);
}

static int header_ok(const struct pra_linux_header *h)
{
	static const uint8_t want[8] = {
		'P', 'R', 'A', 'L', 'N', 'X', '0', '1'
	};

	for (unsigned i = 0; i < 8; i++) {
		if (h->magic[i] != want[i])
			return 0;
	}
	return h->version == PRA_LINUX_VERSION &&
	       h->header_size == PRA_LINUX_HEADER_BYTES &&
	       h->image_lba == PRA_LINUX_IMAGE_LBA &&
	       h->image_size >= 4096 &&
	       h->image_size <= PRA_LINUX_IMAGE_MAX &&
	       h->flags == 0 &&
	       h->load_addr == PRA_LINUX_LOAD_ADDR;
}

/* The arm64 protocol places the Image text_offset bytes above a 2 MiB aligned
 * base and calls the Image start. text_offset is usually 0 in modern kernels;
 * the stock 4.4.23 Image is expected to carry 0x80000 (Huawei's released
 * source sets TEXT_OFFSET to 0x00080000). Reject only offsets that would
 * leave the reserved 2 MiB base window. image_size is the effective in-memory
 * size (file bytes plus BSS), so keep it in sane bounds. */
static int image_ok(const uint8_t *img, uint64_t size, uint64_t base,
                    uintptr_t *load, uint64_t *text_offset)
{
	uint64_t off, image_size;

	if (size < 64)
		return 0;
	off = le64(img + 8);
	image_size = le64(img + 16);
	if (le32(img + 56) != LINUX_IMAGE_MAGIC)
		return 0;
	if (off >= LINUX_TEXT_ALIGN)
		return 0;
	if (image_size < size || image_size > LINUX_INTERNAL_MAX)
		return 0;
	*load = (uintptr_t)(base + off);
	if (*load + image_size > PRA_LINUX_RAM_END)
		return 0;
	*text_offset = off;
	return 1;
}

static int ranges_overlap(uint64_t a, uint64_t alen,
                          uint64_t b, uint64_t blen)
{
	return alen && blen && a < b + blen && b < a + alen;
}

/* ---- CRC-32 (zlib polynomial), matching tools/pra-stage-twrp-kernel.sh - */

static uint32_t crc_table[256];

static void crc32_init(void)
{
	for (uint32_t i = 0; i < 256; i++) {
		uint32_t c = i;

		for (unsigned k = 0; k < 8; k++)
			c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
		crc_table[i] = c;
	}
}

static uint32_t crc32_bytes(const uint8_t *p, uint64_t n)
{
	uint32_t c = 0xffffffffu;

	for (uint64_t i = 0; i < n; i++)
		c = crc_table[(c ^ p[i]) & 0xff] ^ (c >> 8);
	return c ^ 0xffffffffu;
}

/* ---- cache and watchdog ----------------------------------------------- */

static void clean_bytes(uintptr_t start, uintptr_t end)
{
	uint64_t ctr;
	__asm__ volatile("mrs %0, CTR_EL0" : "=r" (ctr));
	uintptr_t line = 4UL << ((ctr >> 16) & 0xf);

	for (uintptr_t p = start & ~(line - 1); p < end; p += line)
		__asm__ volatile("dc cvac, %0" : : "r" (p) : "memory");
	__asm__ volatile("dsb sy" : : : "memory");
}

static void watchdog_off(void)
{
	*(volatile uint32_t *)(WDT + 0xC00) = 0x1ACCE551u;	/* unlock */
	*(volatile uint32_t *)(WDT + 0x008) = 0;		/* disable */
	*(volatile uint32_t *)(WDT + 0x00C) = 1;		/* clear irq */
	*(volatile uint32_t *)(WDT + 0xC00) = 0;		/* relock */
}

/* ---- main ------------------------------------------------------------- */

void pra_linux_try(uintptr_t dtb)
{
	static uint8_t hdr_sector[PRA_LINUX_HEADER_BYTES] __attribute__((aligned(8)));
	static uint8_t first[512] __attribute__((aligned(8)));
	static uint8_t tail[512] __attribute__((aligned(8)));
	uintptr_t initrd_start, initrd_end, image_pa;
	uint64_t dtb_size, image_size, sectors, text_offset;

	/* Only an explicit opt-in may take the staged Image. enter_recovery=1
	 * is set by LK's eRecovery failsafe on every power-on, so it cannot be
	 * the trigger; the initrd properties exist on ordinary boots too. */
	if (!bootarg_has(dtb, "pra_linux=1"))
		return;
	if (!initrd_range(dtb, &initrd_start, &initrd_end))
		return;

	con_puts("linux: recovery initrd present\n");
	con_hex("initrd  ", initrd_start);
	con_hex("initrd e", initrd_end);

	if (pra_sdhci_read(PRA_LINUX_HEADER_LBA, hdr_sector)) {
		con_puts("linux: header unreadable, XNU fallback\n");
		return;
	}

	const struct pra_linux_header *h =
		(const struct pra_linux_header *)hdr_sector;
	if (!header_ok(h)) {
		con_puts("linux: no staged image in preas, XNU fallback\n");
		return;
	}
	image_size = h->image_size;
	con_dec("linux bytes", image_size);
	con_hex("linux crc ", h->image_crc);

	/* Read the Image header before the bulk transfer so a wrong or
	 * misaligned image fails in one CMD17, not after 70k of them. */
	if (pra_sdhci_read(PRA_LINUX_IMAGE_LBA, first)) {
		con_puts("linux: image header unreadable, XNU fallback\n");
		return;
	}
	if (!image_ok(first, image_size, PRA_LINUX_LOAD_ADDR, &image_pa,
	              &text_offset)) {
		con_puts("linux: bad arm64 Image header, XNU fallback\n");
		return;
	}
	con_hex("linux load", image_pa);
	con_hex("linux textoff", text_offset);

	dtb_size = fdt_be32(dtb + 4);
	if (!dtb_size) {
		con_puts("linux: bad DTB size, XNU fallback\n");
		return;
	}
	if (ranges_overlap(image_pa, image_size, dtb, dtb_size) ||
	    ranges_overlap(image_pa, image_size,
	                   initrd_start, initrd_end - initrd_start)) {
		con_puts("linux: load would overlap initrd/DTB, XNU fallback\n");
		return;
	}
	if (image_pa + image_size > PRA_LINUX_RAM_END) {
		con_puts("linux: image does not fit RAM, XNU fallback\n");
		return;
	}

	/* The polled read path is single-sector; ~35 MB is 70k CMD17s. */
	watchdog_off();
	con_puts("linux: reading Image from preas\n");
	for (unsigned i = 0; i < 512; i++)
		((uint8_t *)image_pa)[i] = first[i];
	sectors = (image_size + 511) / 512;
	for (uint64_t i = 1; i < sectors; i++) {
		uint64_t done = i * 512;
		uint8_t *dst = (uint8_t *)(image_pa + done);

		if (image_size - done >= 512) {
			if (pra_sdhci_read(PRA_LINUX_IMAGE_LBA + i, dst)) {
				con_puts("linux: read failed, XNU fallback\n");
				return;
			}
		} else {
			if (pra_sdhci_read(PRA_LINUX_IMAGE_LBA + i, tail)) {
				con_puts("linux: read failed, XNU fallback\n");
				return;
			}
			for (uint64_t j = 0; done + j < image_size; j++)
				dst[j] = tail[j];
		}
		if ((i & 0x1fff) == 0x1fff)
			con_dec("linux MiB", (i + 1) / 2048);
	}

	crc32_init();
	uint32_t crc = crc32_bytes((const uint8_t *)image_pa, image_size);
	if (crc != h->image_crc) {
		con_hex("linux crc got", crc);
		con_hex("linux crc hdr", h->image_crc);
		con_puts("linux: CRC mismatch, XNU fallback\n");
		return;
	}

	clean_bytes(image_pa, image_pa + image_size);
	clean_bytes(dtb, dtb + dtb_size);

	con_hex("linux entry", image_pa);
	con_puts("jumping to Linux\n");

	__asm__ volatile("ic iallu; dsb sy; isb" : : : "memory");
	pra_jump_linux(dtb, image_pa);
}

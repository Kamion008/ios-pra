/* SPDX-License-Identifier: GPL-2.0-only
 * PRA-LX1 loader: on-demand Linux boot from a pre-staged arm64 Image.
 *
 * The bootloader always takes the kernel from `kernel` (p30) and, when the
 * recovery keys are held, takes only the ramdisk from `recovery_ramdisk`
 * (p32), describing it in /chosen as linux,initrd-start/end. The loader can
 * therefore branch on that initrd and boot a Linux Image staged in the
 * otherwise unused `preas` partition (p51).
 *
 * Scratch layout (absolute LBA, 512-byte sectors):
 *
 *   preas p51, first LBA 2097152 (880 MiB)
 *   +0                 one 512-byte header, sector PRA_LINUX_HEADER_LBA
 *   +0 .. +2 MiB       header zone, the remaining sectors stay zero
 *   +2 MiB             uncompressed arm64 Image at PRA_LINUX_IMAGE_LBA
 *
 * 2 MiB of header space puts the Image start on a 2 MiB boundary:
 * 2101248 * 512 = 0x40200000. That also leaves room for a future second
 * image or metadata without moving the first one.
 *
 * The Image is copied to PRA_LINUX_LOAD_ADDR + text_offset. The arm64 boot
 * protocol aligns that 2 MiB base, not text_offset itself: the stock 4.4.23
 * Image on this phone carries text_offset 0x80000, so it lands at 0x30080000,
 * while a modern Image with text_offset 0 lands at 0x30000000. Either way the
 * image and its BSS stay above everything the recovery boot uses: the TWRP
 * ramdisk sits at 0x11000000 and is about 15.2 MB, the live DTB is around
 * 0x07e00000, and this loader plus a XNU payload occupies 0x480000 up to
 * roughly 0x1500000. All of those are below 0x30000000, and the 2 MiB base
 * window plus 128 MiB is still far below the 0x60000000 end of the first RAM
 * bank.
 */
#ifndef PRA_LINUX_BOOT_H
#define PRA_LINUX_BOOT_H

#include <stdint.h>

#define PRA_LINUX_HEADER_LBA    2097152ULL	/* preas p51 first LBA */
#define PRA_LINUX_HEADER_SECTORS 4096ULL	/* 2 MiB header zone */
#define PRA_LINUX_IMAGE_LBA     (PRA_LINUX_HEADER_LBA + PRA_LINUX_HEADER_SECTORS)
#define PRA_LINUX_IMAGE_MAX_MIB 128ULL
#define PRA_LINUX_IMAGE_MAX     (PRA_LINUX_IMAGE_MAX_MIB * 1024ULL * 1024)
#define PRA_LINUX_LOAD_ADDR     0x30000000ULL
#define PRA_LINUX_RAM_END       0x60000000ULL	/* end of the first RAM bank */
#define PRA_LINUX_HEADER_BYTES  512U
#define PRA_LINUX_VERSION       1U

/* The loader accepts this only when the magic, version, size and CRC all
 * match; a blank preas therefore declines and the XNU path runs unchanged. */
struct pra_linux_header {
	uint8_t  magic[8];	/* "PRALNX01" */
	uint32_t version;	/* PRA_LINUX_VERSION */
	uint32_t header_size;	/* PRA_LINUX_HEADER_BYTES */
	uint64_t image_lba;	/* absolute LBA, must equal PRA_LINUX_IMAGE_LBA */
	uint64_t image_size;	/* bytes of Image transferred */
	uint32_t image_crc;	/* zlib/CRC-32 of the image bytes */
	uint32_t flags;		/* 0 */
	uint64_t load_addr;	/* PRA_LINUX_LOAD_ADDR */
	uint8_t  reserved[PRA_LINUX_HEADER_BYTES - 48];
};

_Static_assert(sizeof(struct pra_linux_header) == PRA_LINUX_HEADER_BYTES,
	       "linux header size");

/* If the live DTB describes a recovery initrd, try the staged Linux Image.
 * Returns only on fallback (no initrd, blank scratch, read error, bad Image
 * header or CRC); the caller then continues with the XNU path. */
void pra_linux_try(uintptr_t dtb);

#endif

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Repack an arm64 Image into the PRA boot image with no gzip.

    tools/pra_raw_repack.py IMAGE STOCK_BOOTIMG OUT.img

LK's failsafe path on p27 (erecovery_kernel) loads the kernel region and
expects a flat arm64 Image there: the gzip that shim/pra/build-xnu.sh emits
boots from p27 only some of the time and made the ring log ambiguous. The
packaging is trivial - the stock ANDROID! header with kernel_size pointing at
the Image that follows it - so keep it in the tree instead of in /tmp.

IMAGE is the `Image` file from the build (the same bytes build-xnu.sh gzips).
STOCK_BOOTIMG supplies the 2 KiB header (research/.../pra-xnu-0149.img, any
earlier flashable image, or a stock dump); only its header is used. Page size
must be 2048, which is what this device's header declares.
"""
import struct
import sys
from pathlib import Path

PAGE = 2048
# Offsets in the ANDROID! header: kernel_size, ramdisk_size, second_size,
# dt_size. A raw Image carries nothing else, so the rest are zeroed.
KERNEL_SIZE = 8
RAMDISK_SIZE = 8 + 2 * 4
SECOND_SIZE = 8 + 4 * 4
DT_SIZE = 8 + 8 * 4
# boot-arg string, as written by tools/pra_setcmdline.py
CMDLINE = 0x48
CMDLINE_LEN = 512


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__.strip().splitlines()[2])

    image = Path(argv[1]).read_bytes()
    stock = Path(argv[2]).read_bytes()[:PAGE]
    out = Path(argv[3])

    if stock[:8] != b"ANDROID!":
        sys.exit("error: stock boot image has no ANDROID! magic")
    page = struct.unpack_from("<I", stock, 8 + 7 * 4)[0]
    if page != PAGE:
        sys.exit(f"error: stock page size {page:#x}, expected {PAGE:#x}")
    if image[56:60] != b"ARMd":
        sys.exit("error: input is not an arm64 Image (no ARMd magic at 56)")

    hdr = bytearray(stock)
    struct.pack_into("<I", hdr, KERNEL_SIZE, len(image))
    struct.pack_into("<I", hdr, RAMDISK_SIZE, 0)
    struct.pack_into("<I", hdr, SECOND_SIZE, 0)
    struct.pack_into("<I", hdr, DT_SIZE, 0)

    body = bytes(hdr) + image
    if len(body) % PAGE:
        body += b"\0" * (PAGE - len(body) % PAGE)
    out.write_bytes(body)

    cmdline = bytes(hdr[CMDLINE:CMDLINE + CMDLINE_LEN]).split(b"\0", 1)[0]
    print(f"image   {len(image)} bytes")
    print(f"bootimg {len(body)} bytes ({len(body) // 512} sectors)")
    print(f"cmdline {cmdline.decode('utf-8', 'replace')}")


if __name__ == "__main__":
    main(sys.argv)

#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Build the PRA-LX1 diagnostic kernel as an Android boot.img v0 whose
# "kernel" is gzip(arm64 Image), matching the stock Huawei image.
#
# Toolchain: clang + ld.lld + llvm-objcopy (no aarch64-gcc needed).
set -eu
cd "$(dirname "$0")"
: "${CC:=clang}"
: "${LD:=ld.lld}"
: "${OBJCOPY:=llvm-objcopy}"
: "${STOCK_HEADER:=../../tools/pra_boot_header.bin}"
: "${OUT:=out}"

mkdir -p "$OUT"

ARCH_FLAGS="--target=aarch64-none-elf -march=armv8-a -mgeneral-regs-only -mstrict-align"
CFLAGS="-O2 -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie
        -nostdlib -fno-asynchronous-unwind-tables -fno-unwind-tables
        -Wall -Wextra -Werror $ARCH_FLAGS"

$CC $CFLAGS -c start.S   -o "$OUT/start.o"
$CC $CFLAGS -c console.c -o "$OUT/console.o"
$CC $CFLAGS -c probe.c   -o "$OUT/probe.o"

$LD -static -T link.ld --build-id=none \
    "$OUT/start.o" "$OUT/console.o" "$OUT/probe.o" -o "$OUT/pra-diag.elf"

# Any absolute relocation is fine here (we run at our link address), but
# undefined helpers are not: the image has no C library.
if nm -u "$OUT/pra-diag.elf" | grep -q .; then
    echo "error: undefined symbols:" >&2
    nm -u "$OUT/pra-diag.elf" >&2
    exit 1
fi

$OBJCOPY -O binary "$OUT/pra-diag.elf" "$OUT/image-payload.bin"

# Pad the flat binary through __bss_end so that the bootloader's
# add_device_tree() appends the DTB after the whole runtime footprint,
# not in the middle of our stack or .bss.
BSS_END=$(nm "$OUT/pra-diag.elf" | awk '$3=="__bss_end"{print $1}')
[ -n "$BSS_END" ] || { echo "error: no __bss_end symbol" >&2; exit 1; }
python3 - "$OUT" "$STOCK_HEADER" "$BSS_END" <<'PY'
import gzip, struct, sys, zlib
from pathlib import Path

out = Path(sys.argv[1])
stock_header = Path(sys.argv[2]).read_bytes()
bss_end = int(sys.argv[3], 16)
assert len(stock_header) >= 0x800 and stock_header[:8] == b'ANDROID!'

BASE = 0x480000
payload = bytearray(out.joinpath('image-payload.bin').read_bytes())
image_size = (max(len(payload), bss_end - BASE) + 0xfff) & ~0xfff
payload += b'\0' * (image_size - len(payload))

# arm64 Linux Image header fields (offsets from the start of the payload).
# The 64-byte header itself is emitted by start.S, including the "ARMd"
# magic at 0x38 and res5 at 0x3c. Only the runtime footprint needs filling
# in; writing offset 0x40 here would clobber the first instruction of entry.
struct.pack_into('<Q', payload, 8, 0x80000)        # text_offset
struct.pack_into('<Q', payload, 16, image_size)     # image_size (footprint)
struct.pack_into('<Q', payload, 24, 0x0a)           # LE, 4K pages, any placement

out.joinpath('Image').write_bytes(payload)

gz = gzip.compress(bytes(payload), compresslevel=9, mtime=0)
out.joinpath('kernel.gz').write_bytes(gz)

# Android boot header v0: reuse the stock page verbatim, then replace the
# kernel section. Everything else (addresses, page size, os_version,
# cmdline, Huawei's opaque id bytes) stays as the bootloader expects.
PAGE = struct.unpack_from('<I', stock_header, 8 + 7 * 4)[0]
assert PAGE == 0x800, PAGE
hdr = bytearray(stock_header[:PAGE])
struct.pack_into('<I', hdr, 8 + 0 * 4, len(gz))      # kernel_size
struct.pack_into('<I', hdr, 8 + 2 * 4, 0)            # ramdisk_size
struct.pack_into('<I', hdr, 8 + 4 * 4, 0)            # second_size
struct.pack_into('<I', hdr, 8 + 8 * 4, 0)            # dt_size

body = bytes(hdr) + gz
body += b'\0' * ((-len(body)) % PAGE)
out.joinpath('pra-diag.img').write_bytes(body)

print(f'payload   {len(payload)} bytes ({image_size:#x})')
print(f'gzip      {len(gz)} bytes')
print(f'boot.img  {len(body)} bytes')
PY

# Sanity: decompress what the bootloader will decompress.
python3 - "$OUT" <<'PY'
import gzip, struct, sys
from pathlib import Path
out = Path(sys.argv[1])
gz = out.joinpath('kernel.gz').read_bytes()
raw = gzip.decompress(gz)
assert raw[56:60] == b'ARMd'
assert struct.unpack_from('<Q', raw, 8)[0] == 0x80000
assert struct.unpack_from('<Q', raw, 24)[0] == 0x0a
assert struct.unpack_from('<Q', raw, 16)[0] == len(raw)
print('verified: gzip -> arm64 Image, text_offset 0x80000, image_size aligned')
PY

ls -l "$OUT/Image" "$OUT/kernel.gz" "$OUT/pra-diag.img"

#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Build the PRA-LX1 XNU loader as an Android boot.img v0.
#
#   ./build-xnu.sh                  # loader + handoff test payload
#   PAYLOAD=path ./build-xnu.sh     # loader + a prebuilt SWEETXNU payload
#
# The payload is appended to the flat arm64 Image at the fixed physical
# address 0x500000 (__payload_start), so the bootloader's add_device_tree()
# puts the DTB after it and the loader's bounds check is just dtb-payload.
set -eu
cd "$(dirname "$0")"
: "${CC:=clang}"
: "${LD:=ld.lld}"
: "${OBJCOPY:=llvm-objcopy}"
: "${NM:=llvm-nm}"
: "${STOCK_HEADER:=../../tools/pra_boot_header.bin}"
: "${OUT:=outxnu}"
: "${PAYLOAD:=}"

mkdir -p "$OUT"

ARCH_FLAGS="--target=aarch64-none-elf -march=armv8-a -mgeneral-regs-only -mstrict-align"
CFLAGS="-O2 -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie
        -nostdlib -fno-asynchronous-unwind-tables -fno-unwind-tables
        -Wall -Wextra -Werror $ARCH_FLAGS"

$CC $CFLAGS -c start.S      -o "$OUT/start.o"
$CC $CFLAGS -c console.c    -o "$OUT/console.o"
$CC $CFLAGS -c boot_main.c  -o "$OUT/boot_main.o"
$CC $CFLAGS -c xnu_jump.S   -o "$OUT/xnu_jump.o"

$LD -static -T xnu_boot.ld --build-id=none \
    "$OUT/start.o" "$OUT/console.o" "$OUT/boot_main.o" "$OUT/xnu_jump.o" \
    -o "$OUT/loader.elf"

if $NM -u "$OUT/loader.elf" | grep -q .; then
    echo "error: undefined symbols:" >&2
    $NM -u "$OUT/loader.elf" >&2
    exit 1
fi

PAYLOAD_START=$($NM "$OUT/loader.elf" | awk '$3=="__payload_start"{print $1}')
[ "$PAYLOAD_START" = "0000000000500000" ] || {
    echo "error: __payload_start is $PAYLOAD_START, expected 0x500000" >&2
    exit 1
}
PAYLOAD_SIZE_SYM=$($NM "$OUT/loader.elf" | awk '$3=="pra_payload_size"{print $1}')
[ -n "$PAYLOAD_SIZE_SYM" ] || {
    echo "error: pra_payload_size symbol missing" >&2
    exit 1
}

# The ADT is the source of truth for the XNU window (dram-base/dram-size).
python3 ../../tools/mkadt_pra.py "$OUT/adt-pra.bin"

if [ -z "$PAYLOAD" ]; then
    $CC $CFLAGS -c test_payload.c -o "$OUT/test_payload.o"
    $LD -static -T test_payload.ld --build-id=none \
        "$OUT/test_payload.o" -o "$OUT/test_payload.elf"
    $OBJCOPY -O binary "$OUT/test_payload.elf" "$OUT/test_payload.bin"
    ENTRY=$($NM "$OUT/test_payload.elf" | awk '$3=="test_entry"{print $1}')
    PAYLOAD_END=$($NM "$OUT/test_payload.elf" | awk '$3=="__payload_end"{print $1}')
    [ -n "$ENTRY" ] && [ -n "$PAYLOAD_END" ] || {
        echo "error: test payload symbols missing" >&2
        exit 1
    }
    VMSIZE=$((0x$PAYLOAD_END - 0x88000000))
    python3 ../../tools/mkpayload_flat.py \
        "$OUT/test_payload.bin" 0x88000000 "0x$ENTRY" "$VMSIZE" \
        "$OUT/adt-pra.bin" "$OUT/payload.bin" \
        --cmdline "debug=0x8 serial=0 cpus=1"
else
    cp "$PAYLOAD" "$OUT/payload.bin"
fi

$OBJCOPY -O binary "$OUT/loader.elf" "$OUT/loader.bin"

python3 - "$OUT" "$STOCK_HEADER" "0x$PAYLOAD_SIZE_SYM" <<'PY'
import gzip, struct, sys
from pathlib import Path

out = Path(sys.argv[1])
stock_header = Path(sys.argv[2]).read_bytes()
size_sym = int(sys.argv[3], 0)
loader = out.joinpath('loader.bin').read_bytes()
payload = out.joinpath('payload.bin').read_bytes()

BASE = 0x480000
PAYLOAD_PA = 0x500000
PAYLOAD_OFF = PAYLOAD_PA - BASE
assert len(loader) <= PAYLOAD_OFF, f'loader {len(loader):#x} overlaps payload'
assert payload[:8] == b'SWEETXNU', 'payload magic'

image = bytearray(loader)
image += b'\0' * (PAYLOAD_OFF - len(image))
image += payload
image_size = (len(image) + 0xfff) & ~0xfff
image += b'\0' * (image_size - len(image))

# Tell the loader the exact payload length, so its bounds checks do not
# depend on where the bootloader happens to place the DTB.
size_off = size_sym - BASE
assert 0 <= size_off <= len(loader) - 8, hex(size_off)
struct.pack_into('<Q', image, size_off, len(payload))

assert image[56:60] == b'ARMd', 'loader lost the ARMd magic'
struct.pack_into('<Q', image, 8, 0x80000)        # text_offset
struct.pack_into('<Q', image, 16, image_size)    # image_size (decompressed)
struct.pack_into('<Q', image, 24, 0x0a)          # LE, 4K pages, any placement

out.joinpath('Image').write_bytes(image)
gz = gzip.compress(bytes(image), compresslevel=9, mtime=0)
out.joinpath('kernel.gz').write_bytes(gz)

PAGE = struct.unpack_from('<I', stock_header, 8 + 7 * 4)[0]
assert PAGE == 0x800, PAGE
hdr = bytearray(stock_header[:PAGE])
struct.pack_into('<I', hdr, 8 + 0 * 4, len(gz))      # kernel_size
struct.pack_into('<I', hdr, 8 + 2 * 4, 0)            # ramdisk_size
struct.pack_into('<I', hdr, 8 + 4 * 4, 0)            # second_size
struct.pack_into('<I', hdr, 8 + 8 * 4, 0)            # dt_size

body = bytes(hdr) + gz
body += b'\0' * ((-len(body)) % PAGE)
out.joinpath('pra-xnu.img').write_bytes(body)

print(f'loader    {len(loader)} bytes')
print(f'payload   {len(payload)} bytes')
print(f'image     {image_size:#x} bytes (payload at {PAYLOAD_PA:#x})')
print(f'gzip      {len(gz)} bytes')
print(f'boot.img  {len(body)} bytes')
PY

python3 - "$OUT" "0x$PAYLOAD_SIZE_SYM" <<'PY'
import gzip, struct, sys
from pathlib import Path
out = Path(sys.argv[1])
size_sym = int(sys.argv[2], 0)
raw = gzip.decompress(out.joinpath('kernel.gz').read_bytes())
assert raw[56:60] == b'ARMd'
assert struct.unpack_from('<Q', raw, 8)[0] == 0x80000
assert struct.unpack_from('<Q', raw, 24)[0] == 0x0a
assert struct.unpack_from('<Q', raw, 16)[0] == len(raw)
assert raw[0x80000:0x80008] == b'SWEETXNU'
patched, = struct.unpack_from('<Q', raw, size_sym - 0x480000)
payload_len = len(out.joinpath('payload.bin').read_bytes())
assert patched == payload_len, (hex(patched), hex(payload_len))
print(f'verified: gzip -> arm64 Image, ARMd magic, payload at 0x500000, '
      f'length {payload_len:#x} patched')
PY

ls -l "$OUT/pra-xnu.img"

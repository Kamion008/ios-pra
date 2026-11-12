#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Stage an uncompressed Linux arm64 Image for the PRA-LX1 loader's dual boot.
#
#   tools/pra-stage-twrp-kernel.sh [P30_DUMP]
#
# Run from a PC with exactly one PRA-LX1 in TWRP and adb authorised. P30_DUMP
# is an optional read-only copy of the stock `kernel` partition; without it
# the script pulls p30 over adb. The Image is extracted from that Android boot
# image v0 (page 2048, kernel gzip at offset 2048, kernel_size from the
# header), gunzipped, and written to `preas` (p51) with the loader's 512-byte
# header. Holding vol+ at power-on then boots it; a normal boot still runs XNU.
#
# Only `preas` is written. p30 is read-only and p58/userdata is never opened.
# The GPT is checked so a renamed or moved partition cannot redirect the
# write: preas must still start at absolute LBA 2097152 and p30 at 901120.
set -euo pipefail
dump=${1:-}
# Resolve before cd so a relative P30_DUMP still means the caller's cwd.
case "$dump" in
    ""|/*) ;;
    *) dump="$(pwd)/$dump" ;;
esac
cd "$(dirname "$0")/.."

adb=${ADB:-adb}
hdrfile=shim/pra/linux_boot.h

die() { echo "error: $*" >&2; exit 1; }

[[ -f $hdrfile ]] || die "missing $hdrfile"
command -v python3 >/dev/null || die "python3 is required"

# The C header is the single source of truth for the scratch layout. Only
# literal numeric #defines are parsed here; everything else is derived.
pconst() {
    sed -n "s/^#define[[:space:]]\+$1[[:space:]]\+\(0x[0-9a-fA-F]\+\|[0-9]\+\)[uUlL]*.*/\1/p" \
        "$hdrfile" | head -1
}
header_lba=$(pconst PRA_LINUX_HEADER_LBA)
header_sectors=$(pconst PRA_LINUX_HEADER_SECTORS)
image_max_mib=$(pconst PRA_LINUX_IMAGE_MAX_MIB)
load_addr=$(pconst PRA_LINUX_LOAD_ADDR)
ram_end=$(pconst PRA_LINUX_RAM_END)
header_bytes=$(pconst PRA_LINUX_HEADER_BYTES)
version=$(pconst PRA_LINUX_VERSION)
for v in header_lba header_sectors image_max_mib load_addr ram_end \
         header_bytes version; do
    [[ -n ${!v} ]] || die "cannot read $v from $hdrfile"
done
image_lba=$((header_lba + header_sectors))
header_bytes_dec=$((header_bytes))
image_max_bytes=$((image_max_mib * 1024 * 1024))

# Live GPT facts for this phone.
p30_lba=901120
p30_bytes=$((24 * 1024 * 1024))
p51_name=preas
p51_lba=$header_lba

# ---- device checks ---------------------------------------------------------

$adb get-state >/dev/null 2>&1 || die "no adb device (boot TWRP first)"
twrp=$($adb shell getprop ro.twrp.version 2>/dev/null | tr -d '\r')
[[ -n $twrp ]] || die "device is not TWRP (ro.twrp.version is empty)"
[[ $($adb shell id 2>/dev/null | tr -d '\r') == *uid=0* ]] || \
    die "adb shell is not root; TWRP normally is"

pick_dev() {
    local name=$1 fallback=$2 d real
    for d in "/dev/block/bootdevice/by-name/$name" \
             "/dev/block/by-name/$name" \
             "/dev/block/platform/hi_mci.0/by-name/$name"; do
        real=$($adb shell "readlink -f $d" 2>/dev/null | tr -d '\r')
        if [[ -n $real && $real == /dev/block/* && $real != *"by-name"* ]]; then
            echo "$real"
            return
        fi
    done
    echo "/dev/block/mmcblk0p$fallback"
}

dev_attr() {
    local dev=$1 attr=$2 v
    v=$($adb shell "cat /sys/class/block/$(basename "$dev")/$attr" \
        2>/dev/null | tr -d '\r')
    [[ $v =~ ^[0-9]+$ ]] || \
        die "cannot read /sys/class/block/$(basename "$dev")/$attr"
    echo "$v"
}

preas=$(pick_dev "$p51_name" 51)
p30=$(pick_dev kernel 30)

case "$(basename "$preas")" in
    mmcblk0p30|mmcblk0p58) die "preas resolved to $(basename "$preas"); refusing" ;;
esac

preas_start=$(dev_attr "$preas" start)
preas_sectors=$(dev_attr "$preas" size)
[[ $preas_start -eq $p51_lba ]] || die \
    "$preas starts at LBA $preas_start, expected $p51_lba; refusing to write"

# ---- extract the Image from the stock p30 dump -----------------------------

tmp=$(mktemp -d "${TMPDIR:-/tmp}/pra-stage-kernel.XXXXXX")
trap 'rm -rf "$tmp"' EXIT

if [[ -n $dump ]]; then
    [[ -f $dump ]] || die "no such p30 dump: $dump"
    dump_src=$dump
else
    p30_start=$(dev_attr "$p30" start)
    p30_sectors=$(dev_attr "$p30" size)
    [[ $p30_start -eq $p30_lba ]] || die \
        "$p30 starts at LBA $p30_start, expected $p30_lba; refusing to read"
    [[ $((p30_sectors * 512)) -eq $p30_bytes ]] || die \
        "$p30 is $((p30_sectors * 512)) bytes, expected $p30_bytes"
    echo "dumping p30 read-only..."
    $adb exec-out "dd if=$p30 bs=1048576 2>/dev/null" > "$tmp/p30.img"
    [[ $(stat -c %s "$tmp/p30.img") -eq $p30_bytes ]] || \
        die "short p30 read"
    dump_src=$tmp/p30.img
fi

echo "extracting Image..."
python3 - "$dump_src" "$tmp/stage.bin" "$header_lba" "$header_sectors" \
         "$image_max_bytes" "$load_addr" "$header_bytes_dec" "$version" \
         "$ram_end" <<'PY'
import gzip
import struct
import sys
import zlib
from pathlib import Path

dump_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
header_lba = int(sys.argv[3])
header_sectors = int(sys.argv[4])
image_max = int(sys.argv[5])
load_addr = int(sys.argv[6], 0)
header_bytes = int(sys.argv[7])
version = int(sys.argv[8])
ram_end = int(sys.argv[9], 0)

dump = dump_path.read_bytes()
if dump[:8] != b'ANDROID!':
    sys.exit('p30 dump is not an Android boot image')
kernel_size, = struct.unpack_from('<I', dump, 8)
page_size, = struct.unpack_from('<I', dump, 36)
if page_size != 2048:
    sys.exit(f'boot image page size {page_size}, expected 2048')
if not kernel_size:
    sys.exit('boot image has kernel_size 0 (not the stock p30)')
if page_size + kernel_size > len(dump):
    sys.exit('kernel_size runs past the dump')

kern = dump[page_size:page_size + kernel_size]
if kern[:2] != b'\x1f\x8b':
    sys.exit(f'kernel at offset {page_size} is not gzip')
try:
    image = gzip.decompress(kern)
except OSError as exc:
    sys.exit(f'gunzip failed: {exc}')

if image[56:60] != b'ARM\x64':
    sys.exit('no arm64 Image magic at byte 56')
text_offset, = struct.unpack_from('<Q', image, 8)
image_size, = struct.unpack_from('<Q', image, 16)
# The arm64 protocol aligns the base address, not text_offset: the stock
# 4.4.23 Image carries 0x80000 here, modern kernels carry 0. Keep the offset
# inside the reserved 2 MiB base window so the placement stays predictable.
if text_offset >= 2 * 1024 * 1024:
    sys.exit(f'text_offset {text_offset:#x} does not fit the 2 MiB base window')
if image_size < len(image) or image_size > 256 * 1024 * 1024:
    sys.exit(f'implausible Image image_size {image_size:#x}')
if len(image) > image_max:
    sys.exit(f'Image is {len(image)} bytes, loader limit is {image_max}')

image_pa = load_addr + text_offset
if image_pa + image_size > ram_end:
    sys.exit(f'Image at {image_pa:#x} + {image_size:#x} runs past {ram_end:#x}')

crc = zlib.crc32(image) & 0xffffffff
image_lba = header_lba + header_sectors
hdr = struct.pack('<8sIIQQIIQ', b'PRALNX01', version, header_bytes,
                  image_lba, len(image), crc, 0, load_addr)
hdr += b'\0' * (header_bytes - len(hdr))
zone = hdr + b'\0' * (header_sectors * 512 - len(hdr))
out_path.write_bytes(zone + image)

print(f'  Image        {len(image)} bytes')
print(f'  text_offset  {text_offset:#x}')
print(f'  image_size   {image_size:#x}')
print(f'  load base    {load_addr:#x}')
print(f'  load address {image_pa:#x}')
print(f'  CRC-32       {crc:#010x}')
print(f'  header LBA   {header_lba}')
print(f'  Image LBA    {image_lba}')
print(f'  staged       {len(zone) + len(image)} bytes')
PY

stage=$tmp/stage.bin
stage_bytes=$(stat -c %s "$stage")
stage_sha=$(sha256sum "$stage" | cut -d' ' -f1)

(( stage_bytes <= preas_sectors * 512 )) || die \
    "preas is $((preas_sectors * 512)) bytes, staged payload is $stage_bytes"

# ---- write and verify ------------------------------------------------------

echo "writing $stage_bytes bytes to $preas ..."
if command -v pv >/dev/null; then
    pv -f -s "$stage_bytes" "$stage" | \
        $adb shell "dd of=$preas bs=1048576" || die "write failed"
else
    cat "$stage" | $adb shell "dd of=$preas bs=1048576" || die "write failed"
fi
$adb shell "sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null; true"

echo "reading back..."
blocks=$(( (stage_bytes + 1048575) / 1048576 ))
$adb exec-out "dd if=$preas bs=1048576 count=$blocks 2>/dev/null" \
    > "$tmp/readback.bin"

site_sha=$(head -c "$stage_bytes" "$tmp/readback.bin" | sha256sum | cut -d' ' -f1)
[[ $site_sha == "$stage_sha" ]] || die \
    "readback hash differs (wrote $stage_sha, read $site_sha)"

echo "readback matches: $stage_sha"
echo "staged in $preas at absolute LBA $header_lba (Image LBA $image_lba)"
echo "boot with vol+ held for Linux; normal power-on still runs XNU"

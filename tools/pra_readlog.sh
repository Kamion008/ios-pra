#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Read the PRA console ring (0140/0144) off the phone while TWRP is running.
#
#   tools/pra_readlog.sh [LBA] [SECTORS]
#
# Defaults are the tail of erecovery_kernel (p27): 753664 + 49152 - 8193 =
# 794623, which 0144 picks so that logging never touches the boot image.
# Prints the ring header, then the newest text. The dump itself is kept in
# /tmp/opencode/pra/ring.bin so it can be inspected again without the phone.
#
# The phone must be in TWRP (adb), not booting XNU: nothing of ours speaks
# adb once the kernel takes over.
set -eu

LBA=${1:-794623}
SECTORS=${2:-8193}
OUT=${OUT:-/tmp/opencode/pra/ring.bin}
SERIAL=${PRA_SERIAL:-SERIAL}

mkdir -p "$(dirname "$OUT")"
adb -s "$SERIAL" exec-out dd if=/dev/block/mmcblk0 bs=512 skip="$LBA" \
    count="$SECTORS" 2>/dev/null > "$OUT"
echo "dump: $OUT ($(wc -c < "$OUT") bytes, LBA $LBA + $SECTORS)"

python3 - "$OUT" <<'PY'
import struct
import sys

data = open(sys.argv[1], 'rb').read()
if data[:7] != b'PRALOG1':
    print('no PRALOG1 header; first sector as text:')
    print(data[:512].decode('latin1').replace('\0', '.'))
    raise SystemExit(1)
version, size = struct.unpack('<II', data[8:16])
total, seq = struct.unpack('<QQ', data[16:32])
print(f'version {version} ring {size >> 20} MiB total {total} seq {seq}')
ring = data[512:512 + size]
n = min(total, size)
start = (total - n) % size
buf = ring[start:start + n] if start + n <= size else \
    ring[start:] + ring[:start + n - size]
text = buf.decode('latin1')
print(f'---- newest {n} bytes ----')
print(text[-6000:])
PY

#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Read the PRA console ring (0140/0144) off the phone while TWRP is running.
#
#   tools/pra_readlog.sh [LBA] [SECTORS]
#
# Defaults are the tail of erecovery_kernel (p27): 753664 + 49152 - 8193 =
# 794623, which 0144 picks so that logging never touches the boot image.
#
# Writes the decoded ring to /tmp/opencode/pra/ring.txt, prints a summary of
# the boot (did the root mount, did SpringBoard/backboardd run, which daemons
# are exec'ing in a loop, what crashed), then the newest text.
#
# The phone must be in TWRP (adb), not booting XNU: nothing of ours speaks
# adb once the kernel takes over.
set -eu

LBA=${1:-794623}
SECTORS=${2:-8193}
OUT=${OUT:-/tmp/opencode/pra/ring.bin}
TXT=${TXT:-/tmp/opencode/pra/ring.txt}
SERIAL=${PRA_SERIAL:-SERIAL}

mkdir -p "$(dirname "$OUT")"
adb -s "$SERIAL" exec-out dd if=/dev/block/mmcblk0 bs=512 skip="$LBA" \
    count="$SECTORS" 2>/dev/null > "$OUT"
echo "dump: $OUT ($(wc -c < "$OUT") bytes, LBA $LBA + $SECTORS)"

python3 - "$OUT" "$TXT" <<'PY'
import struct
import sys
import collections

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
open(sys.argv[2], 'w').write(text)

print(f'---- full ring written to {sys.argv[2]} ({n} bytes) ----')

# What the boot actually reached.
marks = [
    ('ADT/shim',      'Pra'),
    ('host mapped',   'PRA eMMC: host'),
    ('GPT parsed',    'PRA EMMC: GPT'),
    ('root device',   'BSD root:'),
    ('mount ok',      'mountroot'),
    ('launchd',       'launchd'),
    ('backboardd',    'backboardd'),
    ('SpringBoard',   'SpringBoard'),
    ('setup/Hello',   'Setup'),
    ('reprobe',       'card busy'),
    ('log write fail','PRA LOG: write failed'),
    ('hfs error',     'hfs_mountfs'),
    ('panic',         'panic'),
]
print('---- boot marks ----')
for label, needle in marks:
    hits = text.count(needle)
    print(f'  {"yes" if hits else "no ":3} {label:16} {hits}')

# Who is being exec'd, and how often: a crash loop shows as a handful of
# names at high counts while everything else has one.
ex = collections.Counter()
for line in text.splitlines():
    if line.startswith('exec '):
        ex[line[5:].split('(')[0].strip()] += 1
print('---- exec counts (top 12) ----')
for name, count in ex.most_common(12):
    print(f'  {count:5}  {name}')

crashes = [l for l in text.splitlines() if l.startswith('CRSH ')]
print(f'---- crashes: {len(crashes)} ----')
seen = {}
for line in crashes:
    key = line.split()[1] if len(line.split()) > 1 else '?'
    seen[key] = seen.get(key, 0) + 1
for name, count in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
    print(f'  {count:5}  {name}')
for line in crashes[:6]:
    print('  ' + line)

print(f'---- newest {min(n, 4000)} bytes ----')
print(text[-4000:])
PY

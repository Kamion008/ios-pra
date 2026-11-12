#!/bin/bash
# Fetch the iPhone X (d22ap) iOS 16.7.16 20H392 root components.
# These are Apple artifacts: keep them out of git (research/ is ignored).
#
# The CDN throttles one connection to roughly 100-150 KB/s. Measured on
# 2026-11-12: a single curl range ran at ~0.5 MB/s while aria2c with 16
# ranges held ~1.9 MB/s, so the whole IPSW is mirrored once (6.17 GB) and
# the members are extracted locally. remotezip then only has value for a
# single small member (e.g. a DeviceTree after the IPSW has been deleted).
#
# 087-86698-044.dmg (OS) is stored in the zip; 087-86593-047.dmg (SystemOS)
# deflates 2.74 GB -> 1.10 GB, so the local extraction also saves transfer.
set -uo pipefail
cd "$(dirname "$0")/.."

URL="https://updates.cdn-apple.com/2025FallFCS/fullrestores/122-77006/1158E502-D76D-4226-AA06-ED5E30CD1111/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw"
OUT=research/ipsw-x
IPSW=$OUT/$(basename "$URL")
MEMBERS=(
    087-86698-044.dmg                        # OS (root filesystem)
    087-86593-047.dmg                        # Cryptex1,SystemOS
    087-86715-047.dmg                        # Cryptex1,AppOS
    Firmware/all_flash/DeviceTree.d22ap.im4p
)
mkdir -p "$OUT"

missing=0
for m in "${MEMBERS[@]}"; do
    [[ -f $OUT/$m ]] || missing=1
done
if (( missing == 0 )); then
    echo "all members present under $OUT"
    exit 0
fi

# Old remotezip leftovers are redundant once the whole IPSW is mirrored.
rm -f "$OUT"/*.dmg.part

want=$(curl -sfIL -4 "$URL" 2>/dev/null | awk 'tolower($1)=="content-length:" {gsub("\r",""); print $2}' | tail -1)
[[ -n ${want:-} ]] || want=0
have=$(stat -c %s "$IPSW" 2>/dev/null || echo 0)
# aria2c writes pieces out of order, so the file's size reaches the full
# length before the last missing piece lands. A lone .aria2 control file is
# the reliable "download unfinished" marker.
if (( have != want )) || [[ -f $IPSW.aria2 ]]; then
    echo "=== mirroring $(basename "$URL") ($have/$want bytes)"
    for attempt in $(seq 1 20); do
        # Apple's CDN throttles and randomly stalls each connection: the
        # default 60 s timeout killed 14 of 16 connections on 2026-11-12 and
        # the mirror fell to 0.1 MB/s. Keep the timeout long, retry forever,
        # and never abort a connection for being slow; aria2c resumes from
        # its .aria2 control file across restarts.
        aria2c --disable-ipv6=true -x16 -s16 -k1M \
            --max-connection-per-server=16 --min-split-size=1M \
            --file-allocation=none --allow-overwrite=true --auto-file-renaming=false \
            --timeout=180 --connect-timeout=20 --max-tries=0 --retry-wait=3 \
            --lowest-speed-limit=0 \
            --console-log-level=warn --summary-interval=60 \
            -d "$OUT" -o "$(basename "$IPSW")" "$URL" && break
        echo "--- aria2c attempt $attempt failed; resuming in 20 s"
        sleep 20
    done
    have=$(stat -c %s "$IPSW" 2>/dev/null || echo 0)
fi
# A short mirror would make zipfile fail on the last member; the per-member
# CRC-32 that zipfile checks during extraction catches quieter corruption.
if (( want > 0 && have != want )); then
    echo "error: $IPSW is $have bytes, expected $want" >&2
    exit 1
fi
ls -l "$IPSW"

python3 - "$IPSW" "$OUT" "${MEMBERS[@]}" <<'PY'
import os
import shutil
import sys
import zipfile

ipsw, out, members = sys.argv[1], sys.argv[2], sys.argv[3:]
with zipfile.ZipFile(ipsw) as z:
    for name in members:
        info = z.getinfo(name)
        dest = os.path.join(out, name)
        if os.path.exists(dest) and os.path.getsize(dest) == info.file_size:
            print(f'have {name} ({info.file_size} bytes)')
            continue
        os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
        print(f'extracting {name} ({info.file_size} bytes)')
        # zipfile verifies the stored CRC-32 when the stream ends.
        with z.open(name) as src, open(dest + '.part', 'wb') as dst:
            shutil.copyfileobj(src, dst, 8 << 20)
        os.replace(dest + '.part', dest)
PY

echo "done"
ls -la "$OUT"

#!/bin/bash
# Fetch the iPhone X (d22ap) iOS 16.7.16 20H392 root components.
# These are Apple artifacts: keep them out of git (research/ is ignored).
#
# The link is slow and remotezip downloads 64 MiB ranges, so every member is
# retried; remotezip resumes a stored member from its .part file.
set -uo pipefail
cd "$(dirname "$0")/.."

URL="https://updates.cdn-apple.com/2025FallFCS/fullrestores/122-77006/1158E502-D76D-4226-AA06-ED5E30CD1111/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw"
OUT=research/ipsw-x
mkdir -p "$OUT"
export CURL_MAX_TIME=${CURL_MAX_TIME:-3600}

fetch() {
    local pattern=$1
    if compgen -G "$OUT/*$pattern" >/dev/null; then
        echo "have $pattern"
        return 0
    fi
    for attempt in $(seq 1 20); do
        echo "=== $pattern attempt $attempt"
        python3 tools/remotezip.py "$URL" "$pattern" "$OUT" && return 0
        echo "--- retrying $pattern in 20 s"
        sleep 20
    done
    echo "FAILED: $pattern" >&2
    return 1
}

fetch 087-86698-044.dmg      # OS
fetch 087-86593-047.dmg      # Cryptex1,SystemOS
fetch 087-86715-047.dmg      # Cryptex1,AppOS
fetch DeviceTree.d22ap.im4p

echo "done"
ls -la "$OUT"

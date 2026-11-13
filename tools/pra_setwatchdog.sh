#!/bin/bash
# Raise Setup's launch watchdog on the PRA iOS root, from TWRP.
#
#   tools/pra_setwatchdog.sh IMAGE [ADDITIVE_SECONDS] [--yes]
#
# IMAGE is a fresh dump of p58 userdata (research/p58-fresh.img). The
# SpringBoard preference file is one allocation block, so the edit is a
# single 4 KiB write at a fixed LBA, followed by a read-back compare.
# Nothing else on the disk is touched: no catalog, no bitmap, no GPT.
#
# The phone's journal is NOT replayed here. If XNU replays the edited
# block the boot still works but the ring log prints "20.00 seconds"
# instead of the new allowance; that is the signal to replay with
# fsck.hfsplus and write the larger block set.
set -euo pipefail
cd "$(dirname "$0")/.."

img=${1:?usage: pra_setwatchdog.sh IMAGE [ADDITIVE_SECONDS] [--yes]}
add=${2:-280}
[[ $add =~ ^[0-9]+$ ]] || { echo "second argument must be additive seconds" >&2; exit 1; }
[[ -f $img ]] || { echo "no such image: $img" >&2; exit 1; }

adb=${ADB:-adb}
serial=${SERIAL:-57U7N17912003349}
adb -s "$serial" shell true >/dev/null 2>&1 || {
    echo "no adb device $serial (boot TWRP first)" >&2
    exit 1
}

mnt=/tmp/opencode/p58ro
plist=/tmp/opencode/sb/com.apple.springboard.plist
mkdir -p "$mnt" /tmp/opencode/sb

echo "== mounting $img read-only =="
loop=$(pkexec losetup --find --show --read-only "$PWD/$img" 2>/dev/null) || {
    echo "losetup failed" >&2
    exit 1
}
cleanup() { pkexec umount "$mnt" 2>/dev/null || true; pkexec losetup -d "$loop" 2>/dev/null || true; }
trap cleanup EXIT

pkexec mount -o ro,noatime "$loop" "$mnt"
pkexec cp "$mnt/private/var/mobile/Library/Preferences/com.apple.springboard.plist" "$plist"
pkexec chown "$(id -u):$(id -g)" "$plist"
echo "current plist: $(stat -c %s "$plist") bytes"
cleanup
trap - EXIT

echo "== patching the image (single block, size-locked) =="
out=$(python3 tools/pra_hfs_watchdog.py "$img" \
        --add "com.apple.purplebuddy=$add" --plist "$plist")
echo "$out"
seek=$(sed -n 's/.*seek=\([0-9]*\).*/\1/p' <<<"$out")
[[ -n $seek ]] || { echo "could not parse the dd seek from the tool output" >&2; exit 1; }
allow=$((20 + add))
echo "expect the ring log to say: allowance of $allow.00 seconds"

if [[ ${3:-} != --yes ]]; then
    read -r -p "write block $seek to /dev/block/mmcblk0? [y/N] " a
    [[ $a == [yY] ]] || { echo "aborted"; exit 1; }
fi

echo "== writing 4 KiB to LBA $seek =="
$adb -s "$serial" push /tmp/opencode/plist_block.bin /tmp/plist_block.bin >/dev/null
$adb -s "$serial" shell "dd if=/tmp/plist_block.bin of=/dev/block/mmcblk0 bs=4096 seek=$seek count=1 2>&1 | tail -1"
echo "== read-back compare =="
local_sha=$(sha256sum /tmp/opencode/plist_block.bin | cut -d' ' -f1)
dev_sha=$($adb -s "$serial" shell "dd if=/dev/block/mmcblk0 bs=4096 skip=$seek count=1 2>/dev/null" |
          sha256sum | cut -d' ' -f1)
echo "local $local_sha"
echo "device $dev_sha"
[[ $local_sha == "$dev_sha" ]] || { echo "READ-BACK MISMATCH" >&2; exit 1; }
echo "block matches"
rm -f /tmp/opencode/plist_block.bin "$plist"
echo
echo "next: tools/pra_flash_skip.sh research/pra-artifacts/pra-xnu-0151.img"

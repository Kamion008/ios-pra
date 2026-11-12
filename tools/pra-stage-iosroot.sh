#!/bin/bash
# Write a PC-side HFS+ iOS root image to the PRA-LX1 userdata partition.
#
#   tools/pra-stage-iosroot.sh IMAGE [--yes]
#
# The phone must be in TWRP with adb authorised: fastboot flash userdata and
# fastboot boot are blocked by the Huawei allowlist, and the image is larger
# than TWRP's ramdisk, so the image is streamed from the PC over adb stdin.
#
# THIS ERASES ANDROID USER DATA on mmcblk0p58. Bootloaders, recovery, modem,
# persist and every other partition are untouched.
set -euo pipefail
cd "$(dirname "$0")/.."

img=${1:?usage: pra-stage-iosroot.sh IMAGE [--yes]}
yes=${2:-}
[[ -f $img ]] || { echo "no such image: $img" >&2; exit 1; }

geom=research/gpt/geometry.env
[[ -f $geom ]] || {
    echo "missing $geom; run tools/pra-gpt-resize.py and tools/pra-flash-gpt.sh first" >&2
    exit 1
}
userdata_bytes=$(sed -n 's/^USERDATA_BYTES=//p' "$geom")
[[ -n $userdata_bytes ]] || { echo "no USERDATA_BYTES in $geom" >&2; exit 1; }
img_bytes=$(stat -c %s "$img")
(( img_bytes <= userdata_bytes )) || {
    echo "error: image is $img_bytes bytes, userdata is $userdata_bytes" >&2
    exit 1
}

adb=${ADB:-adb}
$adb shell true >/dev/null 2>&1 || { echo "no adb device (boot TWRP first)" >&2; exit 1; }
serial=$($adb get-serialno)
echo "adb device: $serial"

dev=""
for d in /dev/block/bootdevice/by-name/userdata /dev/block/by-name/userdata \
         /dev/block/platform/hi_mci.0/by-name/userdata; do
    if $adb shell "[ -e $d ]" 2>/dev/null; then
        dev=$($adb shell "readlink -f $d" | tr -d '\r')
        break
    fi
done
if [[ -z $dev ]]; then
    dev=/dev/block/mmcblk0p58
    echo "no by-name link; assuming $dev"
fi
read -r sectors < <($adb shell "cat /sys/class/block/$(basename "$dev")/size" | tr -d '\r')
[[ -n ${sectors:-} ]] || { echo "cannot read $dev size" >&2; exit 1; }
if (( sectors * 512 != userdata_bytes )); then
    echo "error: $dev is $((sectors * 512)) bytes, expected $userdata_bytes" >&2
    exit 1
fi
echo "target: $dev, $userdata_bytes bytes"
echo "image:  $img, $img_bytes bytes"

if [[ $yes != --yes ]]; then
    read -r -p "Erase Android user data and write $img to $dev? [type yes] " a
    [[ $a == yes ]] || { echo "aborted"; exit 1; }
fi

# TWRP auto-mounts /data; unmount so nothing writes behind the dd.
$adb shell "umount /data 2>/dev/null; umount /sdcard 2>/dev/null; true"

echo "streaming image..."
if command -v pv >/dev/null; then
    pv "$img" | $adb shell "dd of=$dev bs=4M conv=fsync 2>/dev/null"
else
    cat "$img" | $adb shell "dd of=$dev bs=4M conv=fsync 2>/dev/null"
fi
$adb shell "sync"

# Compare the HFS+ volume header region (offset 1024, 2 KiB) on both sides.
$adb exec-out "dd if=$dev bs=1024 skip=1 count=2 2>/dev/null" > /tmp/pra-stage-readback.bin
dd if="$img" bs=1024 skip=1 count=2 2>/dev/null > /tmp/pra-stage-source.bin
if cmp -s /tmp/pra-stage-readback.bin /tmp/pra-stage-source.bin; then
    echo "readback matches (HFS+ volume header at 1024)"
else
    echo "error: readback differs from the image" >&2
    exit 1
fi
echo "done; boot XNU with rd=sdhcroot0 emmcwrite=1"

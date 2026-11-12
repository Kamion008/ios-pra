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

# p58 userdata from the stock GPT: first LBA 10715136, 10031104 KiB.
userdata_kib=10031104
userdata_bytes=$((userdata_kib * 1024))
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

# TWRP's dd (toolbox) rejects "4M" and has conv=fsync compiled out, and hiding
# its stderr made a failed stream look like a fast success. Use a numeric block
# size, keep the output, and sync from the shell afterwards.
echo "streaming image..."
if command -v pv >/dev/null; then
    if ! pv -f -s "$img_bytes" "$img" | $adb shell "dd of=$dev bs=1048576"; then
        echo "error: streaming to $dev failed" >&2
        exit 1
    fi
else
    if ! cat "$img" | $adb shell "dd of=$dev bs=1048576"; then
        echo "error: streaming to $dev failed" >&2
        exit 1
    fi
fi
$adb shell "sync"

# The primary volume header (offset 1024) and the alternate one (1024 bytes
# before the end) are both written sequentially, so comparing them proves the
# write started and ended where it should.
for spec in "primary 1 2" "alternate $((userdata_bytes / 1024 - 1)) 1"; do
    set -- $spec
    name=$1 skip=$2 count=$3
    $adb exec-out "dd if=$dev bs=1024 skip=$skip count=$count 2>/dev/null" > "/tmp/pra-stage-$name.bin"
    dd if="$img" bs=1024 skip=$skip count=$count 2>/dev/null > "/tmp/pra-stage-source.bin"
    if ! cmp -s "/tmp/pra-stage-$name.bin" "/tmp/pra-stage-source.bin"; then
        echo "error: $name volume header readback differs from the image" >&2
        exit 1
    fi
    echo "readback matches: $name volume header"
done
echo "done; boot XNU with rd=sdhcroot0 emmcwrite=1"

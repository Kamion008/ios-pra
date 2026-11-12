#!/bin/bash
# Write the resized GPT (bigger userdata, Android-only partitions dropped) to
# the PRA-LX1 eMMC from TWRP.
#
#   tools/pra-flash-gpt.sh [--yes]
#
# Requires research/gpt/{gpt-primary.bin,geometry.env} from
# tools/pra-gpt-resize.py. The current primary GPT is dumped to
# research/gpt/device-gpt-lba1-33.bin and must hash to OLD_ENTRIES_SHA256
# before anything is written; if it does not, the phone is not the table we
# generated from and we abort.
#
# Sector 0 (the protective MBR, size field 0 on this Huawei table) is left
# alone. Nothing else on the disk is touched: the new entries only zero the
# Android-only partitions and extend userdata backwards.
set -euo pipefail
cd "$(dirname "$0")/.."

yes=${1:-}
blob=research/gpt/gpt-primary.bin
geom=research/gpt/geometry.env
[[ -f $blob && -f $geom ]] || {
    echo "missing $blob or $geom; run tools/pra-gpt-resize.py first" >&2
    exit 1
}
. "$geom"

adb=${ADB:-adb}
$adb shell true >/dev/null 2>&1 || { echo "no adb device (boot TWRP first)" >&2; exit 1; }
echo "adb device: $($adb get-serialno)"

out=research/gpt/device-gpt-lba1-33.bin
tail=research/gpt/device-gpt-tail33.bin
echo "dumping current GPT..."
$adb exec-out "dd if=/dev/block/mmcblk0 bs=512 skip=1 count=33 2>/dev/null" > "$out"
$adb exec-out "dd if=/dev/block/mmcblk0 bs=512 skip=$((TOTAL_SECTORS - 33)) count=33 2>/dev/null" > "$tail"
[[ $(stat -c %s "$out") == 16896 && $(stat -c %s "$tail") == 16896 ]] || {
    echo "short read from /dev/block/mmcblk0" >&2
    exit 1
}

python3 - "$out" <<'EOF' || exit 1
import sys
d = open(sys.argv[1], 'rb').read()
if d[:8] != b'EFI PART':
    sys.exit('no EFI PART at LBA 1')
EOF

old=$(tail -c +513 "$out" | sha256sum | cut -d' ' -f1)
if [[ $old != "$OLD_ENTRIES_SHA256" ]]; then
    echo "error: device entry array is $old" >&2
    echo "       expected $OLD_ENTRIES_SHA256" >&2
    echo "       this is not the GPT the new table was derived from; refusing" >&2
    exit 1
fi

backup_present=0
if [[ $(head -c 8 "$tail") == "EFI PART" ]]; then
    backup_present=1
fi
if [[ $backup_present == 1 && ! -f research/gpt/gpt-backup.bin ]]; then
    echo "error: the device has a backup GPT at LBA $((TOTAL_SECTORS - 33));" >&2
    echo "       regenerate with --layout std so primary and backup match:" >&2
    echo "       tools/pra-gpt-resize.py --disk <dump> --out research/gpt --layout std" >&2
    exit 1
fi
echo "current GPT matches; backup GPT at tail: $backup_present"

echo "new layout: userdata first=$USERDATA_FIRST last=$USERDATA_LAST"
echo "            sectors=$USERDATA_SECTORS bytes=$USERDATA_BYTES ($((USERDATA_BYTES / 1024 / 1024)) MiB)"
echo "dropped: preas preavs system cust version vendor product"

if [[ $yes != --yes ]]; then
    read -r -p "Write the new primary GPT to /dev/block/mmcblk0? [type yes] " a
    [[ $a == yes ]] || { echo "aborted"; exit 1; }
fi

$adb push "$blob" /tmp/pra-gpt-primary.bin >/dev/null
[[ -f research/gpt/gpt-backup.bin ]] && $adb push research/gpt/gpt-backup.bin /tmp/pra-gpt-backup.bin >/dev/null

echo "writing primary GPT at LBA 1..."
$adb shell "dd if=/tmp/pra-gpt-primary.bin of=/dev/block/mmcblk0 bs=512 seek=1 conv=fsync 2>/dev/null"
if [[ -f research/gpt/gpt-backup.bin ]]; then
    echo "writing backup GPT at LBA $((TOTAL_SECTORS - 33))..."
    $adb shell "dd if=/tmp/pra-gpt-backup.bin of=/dev/block/mmcblk0 bs=512 seek=$((TOTAL_SECTORS - 33)) conv=fsync 2>/dev/null"
fi
$adb shell "sync; rm -f /tmp/pra-gpt-primary.bin /tmp/pra-gpt-backup.bin"

echo "reading back..."
$adb exec-out "dd if=/dev/block/mmcblk0 bs=512 skip=1 count=33 2>/dev/null" > /tmp/pra-gpt-readback.bin
cmp -s /tmp/pra-gpt-readback.bin "$blob" || { echo "error: readback differs" >&2; exit 1; }
new=$(tail -c +513 /tmp/pra-gpt-readback.bin | sha256sum | cut -d' ' -f1)
[[ $new == "$NEW_ENTRIES_SHA256" ]] || { echo "error: entry array hash $new" >&2; exit 1; }

echo "GPT written. Reboot recovery so the kernel re-reads the table:"
echo "  adb reboot recovery"
echo "then check: adb shell blockdev --getsize64 /dev/block/mmcblk0p58"
echo "expect $USERDATA_BYTES bytes"

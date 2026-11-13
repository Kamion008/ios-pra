#!/bin/sh
# Write a raw PRA XNU image to the eRecovery kernel partition from TWRP,
# verify the readback, and reboot into it.
#
#   tools/pra_flash_skip.sh IMAGE
#
# p27 (`erecovery_kernel`) is the partition LK's failsafe actually loads on a
# plain power-on; it starts at LBA 753664 and is 49152 sectors (24 MiB), so
# 368 * 1 MiB is the same offset with a bs toybox accepts (it rejects bs=1M).
# Ops allowlist: p27 only, never p30/p32 and never the bootloaders.
set -eu

cd "$(dirname "$0")/.."
IMG=${1:?usage: pra_flash_skip.sh IMAGE}
S=57U7N17912003349
SEEK_MIB=368
PART_SECTORS=49152

[ -f "$IMG" ] || { echo "no such image: $IMG" >&2; exit 1; }
BYTES=$(stat -c %s "$IMG")
[ $((BYTES % 512)) -eq 0 ] || { echo "$IMG is not sector-aligned" >&2; exit 1; }
SECTORS=$((BYTES / 512))
[ "$SECTORS" -le "$PART_SECTORS" ] || {
	echo "$IMG needs $SECTORS sectors, p27 holds $PART_SECTORS" >&2; exit 1; }

WANT=$(sha256sum "$IMG" | cut -d' ' -f1)
echo "image:   $IMG ($BYTES B, $SECTORS sectors, sha256 $WANT)"

adb -s "$S" get-state >/dev/null 2>&1 || { echo "no adb device $S" >&2; exit 1; }

# Do not boot XNU off a flat battery: the boot is an hour of full CPU.
CAP=$(adb -s "$S" shell 'cat /sys/class/power_supply/Battery/capacity' 2>/dev/null | tr -d '\r')
case "$CAP" in
''|*[!0-9]*) echo "warning: battery capacity unreadable, assuming the user decided" ;;
*) if [ "$CAP" -lt 40 ]; then
	echo "battery at ${CAP}% (< 40%), not flashing" >&2
	exit 1
fi ;;
esac

adb -s "$S" push "$IMG" /tmp/p.img >/dev/null
adb -s "$S" shell "dd if=/tmp/p.img of=/dev/block/mmcblk0 bs=1048576 seek=$SEEK_MIB 2>&1 | tail -1; sync"

GOT=$(adb -s "$S" shell "dd if=/dev/block/mmcblk0 bs=512 skip=753664 count=$SECTORS 2>/dev/null | sha256sum" | cut -d' ' -f1 | tr -d '\r')
echo "readback: $GOT"
[ "$GOT" = "$WANT" ] || { echo "MISMATCH, not rebooting" >&2; exit 1; }

adb -s "$S" reboot
echo "rebooting into XNU"

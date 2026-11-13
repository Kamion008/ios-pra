#!/bin/sh
# Wait for the p58 dump to close, then flash the execskip image to p27 and
# reboot. Done as one job so the dump read and the p27 write never overlap.
set -eu

cd /home/kamion008/Ai/ios/ios-pra
S=57U7N17912003349
IMG=/tmp/opencode/pra/pra-xnu-skip-raw.img
WANT=10271850496          # 20062208 sectors * 512
i=0
while :; do
	size=$(stat -c %s research/p58-20261113.img 2>/dev/null || echo 0)
	[ "$size" -ge "$WANT" ] && break
	grep -q 'dump done' /tmp/opencode/pra/p58dump.log 2>/dev/null && break
	i=$((i + 1))
	[ "$i" -gt 180 ] && { echo "dump did not finish in time (size $size)"; exit 1; }
	sleep 5
done

echo "dump closed: $(stat -c %s research/p58-20261113.img) bytes"
sync

adb -s "$S" push "$IMG" /tmp/p.img >/dev/null
adb -s "$S" shell 'dd if=/tmp/p.img of=/dev/block/mmcblk0 bs=1048576 seek=368 2>&1 | tail -1; sync'
readback=$(adb -s "$S" shell 'dd if=/dev/block/mmcblk0 bs=512 skip=753664 count=33220 2>/dev/null | sha256sum' | cut -d' ' -f1)
echo "p27 readback: $readback"
echo "expected:     c338c680e905140d04d8e14c367d716f07a9f9edb22bfb7571d2fc65cf61fa26"
[ "$readback" = "c338c680e905140d04d8e14c367d716f07a9f9edb22bfb7571d2fc65cf61fa26" ] || {
	echo "MISMATCH, not rebooting"; exit 1; }
adb -s "$S" reboot
echo "rebooting into XNU"

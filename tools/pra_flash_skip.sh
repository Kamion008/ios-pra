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
S=${PRA_SERIAL:?export PRA_SERIAL (serials stay out of git)}
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

# ===========================================================================
# !! HARD GATE: the image's cmdline must carry the critical PRA boot args.  !!
# !! Boots without these failed on the phone, exactly, every time:          !!
# !!   cpus=4              - cpus=1 hangs the SMP boot                      !!
# !!   no emmcmulti needed as of 0164: the driver default is per-sector     !!
# !!                         CMD17 again. The flood boots ran 0142's        !!
# !!                         UNFIXED CMD18 (0148 was silently skipped by    !!
# !!                         CI for weeks - "card busy skip read" floods). !!
# !!                         emmcmulti=1 is the one-off CMD23 opt-in        !!
# !!                         experiment - see emmc-work WORKLOG.            !!
# !!   pralog=1 praloglba=794623 - no eMMC ring -> all boot evidence lost   !!
# !!   wdt=-1              - watchdog reboots the panic off the screen      !!
# !! This gate exists because agents keep "simplifying" the cmdline. To     !!
# !! flash a deliberate experiment anyway: PRA_ALLOW_ANY_CMDLINE=1          !!
# ===========================================================================
if ! python3 - "$IMG" <<'EOF'
import gzip, sys, zlib
data = open(sys.argv[1], "rb").read()
try:
	dec = gzip.decompress(data[0x800:])
except Exception:
	dec = zlib.decompressobj().decompress(data[0x800:])
i = dec.find(b"debug=0xc")
cmd = dec[i:dec.find(b"\x00", i)] if i >= 0 else b""
missing = [a.decode() for a in (
	b"cpus=4", b"rd=sdhcroot0", b"emmcroot=userdata", b"emmcprobe=1",
	b"emmcwrite=1", b"rootrw=1", b"emmcstats=1",
	b"pralog=1", b"praloglba=794623", b"wdt=-1", b"wdt_test=no_user_checkin",
) if a not in cmd]
print("cmdline in image (%d B): %s" % (len(cmd), cmd.decode(errors="replace")))
if missing:
	print("REFUSING TO FLASH: cmdline is MISSING critical args:", " ".join(missing))
	print("  cpus=1 hangs; missing pralog=1 -> no eMMC ring;")
	print("  missing wdt=-1 -> panic rebooted.")
	print("  Re-package with tools/pra_package.sh (correct args are its default),")
	print("  or set PRA_ALLOW_ANY_CMDLINE=1 to flash this experiment anyway.")
	sys.exit(1)
print("cmdline OK: all 11 critical args present")
EOF
then
	if [ "${PRA_ALLOW_ANY_CMDLINE:-0}" != "1" ]; then
		echo "=============================================================" >&2
		echo "!!! CMDLINE GATE FAILED - see the REFUSING TO FLASH output !!!" >&2
		echo "=============================================================" >&2
		exit 1
	fi
	echo "PRA_ALLOW_ANY_CMDLINE=1 set - flashing despite cmdline mismatch"
fi

adb -s "$S" get-state >/dev/null 2>&1 || { echo "no adb device $S" >&2; exit 1; }

# Do not boot XNU off a flat battery: the boot is an hour of full CPU. 25%
# is enough because the flashing phone is always USB-connected, and USB
# charges it (the BQ25892 keeps the bootloader's autonomous charging
# through the XNU boot; a plugged-in phone stays flat or gains %).
CAP=$(adb -s "$S" shell 'cat /sys/class/power_supply/Battery/capacity' 2>/dev/null | tr -d '\r')
case "$CAP" in
''|*[!0-9]*) echo "warning: battery capacity unreadable, assuming the user decided" ;;
*) if [ "$CAP" -lt 25 ]; then
	echo "battery at ${CAP}% (< 25%), not flashing" >&2
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

#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Package a built PRA XNU kernel into the loader boot image.
#
#   tools/pra_package.sh KERNEL [RAMDISK]
#   tools/pra_package.sh KERNEL [RAMDISK]   (CMDLINE env to override - see below)
#
# KERNEL is the Mach-O from the CI artifact (kernel.development.pra). The
# ADT is regenerated from tools/mkadt_pra.py, so its dram-base/size and the
# loader's window cannot drift. With RAMDISK, mkpayload appends it after the
# kernel and adds /chosen/memory-map RAMDisk (boot with rd=md0).
#
# ===========================================================================
# !! THE CMDLINE MATTERS. DO NOT "SIMPLIFY" IT. DO NOT SHIP A DEFAULT THAT   !!
# !! DROPS ARGS. Every boot that skipped these args failed on the phone:     !!
# !!                                                                        !!
# !!   cpus=1              -> hangs (SMP boot never completes)              !!
# !!   emmcmulti=0         -> 0001 makes CMD18 multi-block reads default;   !!
# !!                          do NOT put emmcmulti=0 back without reading   !!
# !!                          research/driver-specs/emmc-work/WORKLOG.md:   !!
# !!                          the old wedge (soft reset without CMD12) is   !!
# !!                          fixed in-driver and the ladder bounds it;      !!
# !!                          emmcmulti=0 or emmcmulti=2 remain escape       !!
# !!                          hatches for one-off CMDLINE experiments only   !!
# !!   missing pralog=1    -> no eMMC ring at all -> every boot's evidence  !!
# !!                          is lost (this is the panic-capture path)      !!
# !!   missing wdt=-1      -> watchdog reboots the panic off the screen     !!
# !!                                                                        !!
# !! The DEFAULT below is the exact cmdline of every boot that reached the  !!
# !! daemons (0153 through 0158b, pra_session_compact_transcript.md:1343).  !!
# !! Both scripts (this one and pra_flash_skip.sh) VERIFY the packaged      !!
# !! image carries the critical args and refuse otherwise. Override with    !!
# !! CMDLINE=... only for deliberate experiments, and expect the flash      !!
# !! script to demand PRA_ALLOW_ANY_CMDLINE=1.                              !!
# ===========================================================================
set -eu
cd "$(dirname "$0")/.."

KERNEL=${1:?usage: pra_package.sh KERNEL [RAMDISK]}
RAMDISK=${2:-}
OUT=shim/pra/outxnu
mkdir -p "$OUT"

python3 tools/mkadt_pra.py "$OUT/adt-pra.bin"

# The proven-good cmdline (0153..0158b boots), with emmcmulti=0 dropped by
# 0001: CMD18 reads are now the driver default with the ladder + stop fixes
# in-driver (bsd/dev/pra_sdhci.c), so no boot arg is needed to enable them
# and emmcmulti=0 stays an escape hatch, not a critical arg. cpus=4,
# pralog=1 praloglba=794623 (the eMMC ring at the erecovery tail), wdt=-1
# (panic stays on screen). Keep in sync with AGENTS.md.
: "${CMDLINE:=debug=0xc serial=3 cpus=4 keepsyms=1 rd=sdhcroot0 emmcroot=userdata emmcprobe=1 emmcwrite=1 rootrw=1 unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 emmcstats=1 pralog=1 praloglba=794623 sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1 sweetfb_hz=1 sweetsample=Setup praexecskip=locationd,WirelessRadioManagerd,fairplayd.H2,bluetoothd,nanotimekitcompaniond,CommCenter}"

if [ "${CMDLINE}" != "debug=0xc serial=3 cpus=4 keepsyms=1 rd=sdhcroot0 emmcroot=userdata emmcprobe=1 emmcwrite=1 rootrw=1 unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 emmcstats=1 pralog=1 praloglba=794623 sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1 sweetfb_hz=1 sweetsample=Setup praexecskip=locationd,WirelessRadioManagerd,fairplayd.H2,bluetoothd,nanotimekitcompaniond,CommCenter" ]; then
	echo "=============================================================" >&2
	echo "WARNING: non-default CMDLINE override - every dropped arg has" >&2
	echo "  a known phone failure mode (see the block in this script)." >&2
	echo "=============================================================" >&2
fi

set -- "$KERNEL" "$OUT/adt-pra.bin" "$OUT/payload.bin"
[ -n "$CMDLINE" ] && set -- "$@" --cmdline "$CMDLINE"
[ -n "$RAMDISK" ] && set -- "$@" --ramdisk "$RAMDISK"
python3 tools/mkpayload.py "$@"

PAYLOAD="$(pwd)/$OUT/payload.bin" shim/pra/build-xnu.sh

# The kernel partition is 24 MiB; a larger boot.img cannot be flashed.
SIZE=$(wc -c < "$OUT/pra-xnu.img")
if [ "$SIZE" -gt 25165824 ]; then
    echo "error: $OUT/pra-xnu.img is $SIZE bytes, over the 24 MiB kernel partition" >&2
    echo "       boot without the ramdisk, or put the root on eMMC" >&2
    exit 1
fi

# Hard gate: the packaged image must carry the critical args. The cmdline
# lives in the gzip'd payload at image offset 0x800, string at 0x80048.
python3 - "$OUT/pra-xnu.img" <<'EOF'
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
    print("FATAL: packaged cmdline is MISSING critical args:", " ".join(missing))
    print("       the phone WILL fail (cpus=1 hang / no ring / watchdog)")
    sys.exit(1)
print("cmdline OK: all 11 critical args present")
EOF

echo
echo "ready: $OUT/pra-xnu.img ($SIZE bytes)"
# AGENTS.md: keep device serials out of git; the flasher supplies one.
SERIAL="${PRA_SERIAL:-SERIAL}"
echo "flash: fastboot -s $SERIAL flash kernel $OUT/pra-xnu.img"
echo "boot:  fastboot -s $SERIAL reboot"

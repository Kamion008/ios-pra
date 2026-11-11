#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Package a built PRA XNU kernel into the loader boot image.
#
#   tools/pra_package.sh KERNEL [RAMDISK]
#
# KERNEL is the Mach-O from the CI artifact (kernel.development.pra). The
# ADT is regenerated from tools/mkadt_pra.py, so its dram-base/size and the
# loader's window cannot drift. With RAMDISK, mkpayload appends it after the
# kernel and adds /chosen/memory-map RAMDisk (boot with rd=md0).
set -eu
cd "$(dirname "$0")/.."

KERNEL=${1:?usage: pra_package.sh KERNEL [RAMDISK]}
RAMDISK=${2:-}
OUT=shim/pra/outxnu
mkdir -p "$OUT"

python3 tools/mkadt_pra.py "$OUT/adt-pra.bin"

: "${CMDLINE:=debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress}"

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

echo
echo "ready: $OUT/pra-xnu.img ($SIZE bytes)"
# AGENTS.md: keep device serials out of git; the flasher supplies one.
SERIAL="${PRA_SERIAL:-SERIAL}"
echo "flash: fastboot -s $SERIAL flash kernel $OUT/pra-xnu.img"
echo "boot:  fastboot -s $SERIAL reboot"

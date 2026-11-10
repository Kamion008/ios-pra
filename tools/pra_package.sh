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

if [ -n "$RAMDISK" ]; then
    python3 tools/mkpayload.py "$KERNEL" "$OUT/adt-pra.bin" "$OUT/payload.bin" \
        --ramdisk "$RAMDISK"
else
    python3 tools/mkpayload.py "$KERNEL" "$OUT/adt-pra.bin" "$OUT/payload.bin"
fi

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
echo "flash: fastboot -s 57U7N17912003349 flash kernel $OUT/pra-xnu.img"
echo "boot:  fastboot -s 57U7N17912003349 reboot"

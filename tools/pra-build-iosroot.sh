#!/bin/bash
# Build the iPhone X (d22ap) iOS 16.7.16 HFS+ root image on the PC.
#
#   sudo tools/pra-build-iosroot.sh [--full] [SIZE]
#
# Needs the three DMGs fetched by tools/pra-fetch-ipsw.sh, apfs-fuse and
# hfsprogs.
#
#   (default)  research/iosroot/ios16-root.img        trimmed, SIZE 9796M
#              that is the whole stock userdata partition (p58, 10031104 KiB
#              = 9.57 GiB); mkiosroot.sh drops only data no first-boot UI
#              loads, so Setup.app, the setup panes and the staged apps stay.
#   --full     research/iosroot/ios16-root-full.img   complete payload, SIZE 12G
#              keeps every file; needs a bigger partition than stock userdata,
#              so it is for a future GPT resize, not for staging today.
#
# The two builds never overwrite each other and both are kept.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ${EUID} != 0 ]]; then
    echo "run as root: iOS UID/GID values are part of the boot contract" >&2
    exit 2
fi

os=research/ipsw-x/087-86698-044.dmg
sysos=research/ipsw-x/087-86593-047.dmg
appos=research/ipsw-x/087-86715-047.dmg

full=0
if [[ ${1:-} == --full ]]; then
    full=1
    shift
fi
if (( full )); then
    out=research/iosroot/ios16-root-full.img
    size=${1:-12G}
else
    out=research/iosroot/ios16-root.img
    size=${1:-9796M}
fi

for f in "$os" "$sysos" "$appos"; do
    [[ -f $f ]] || { echo "missing $f (run tools/pra-fetch-ipsw.sh)" >&2; exit 1; }
done
command -v apfs-fuse >/dev/null || { echo "apfs-fuse missing" >&2; exit 1; }
command -v mkfs.hfsplus >/dev/null || { echo "hfsprogs missing" >&2; exit 1; }

mkdir -p "$(dirname "$out")"
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }

# p58 userdata from the stock GPT: first LBA 10715136, 10031104 KiB.
userdata_kib=10031104
want_kib=$(numfmt --from=iec "$size" | awk '{print int($1/1024)}')
if (( full )); then
    echo "full build: $size (${want_kib} KiB); this will NOT fit the ${userdata_kib} KiB userdata partition"
else
    if (( want_kib > userdata_kib )); then
        echo "error: $size does not leave room in the ${userdata_kib} KiB userdata partition" >&2
        exit 1
    fi
    echo "trimmed build: $size (${want_kib} KiB), userdata ${userdata_kib} KiB"
fi

MKROOT_TRIM=$((1 - full)) tools/mkiosroot.sh "$os" "$sysos" "$appos" "$out" "$size"
ls -l "$out"
echo "stage with: tools/pra-stage-iosroot.sh $out"

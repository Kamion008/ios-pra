#!/bin/bash
# Build the iPhone X (d22ap) iOS 16.7.16 HFS+ root image on the PC.
#
#   sudo tools/pra-build-iosroot.sh [SIZE]
#
# Needs the three DMGs fetched by tools/pra-fetch-ipsw.sh, apfs-fuse and
# hfsprogs. The image must fit the Huawei userdata partition (p58,
# 10,031,104 KiB = 9.57 GiB); SIZE defaults to 9.2G.
#
# This is the donor mkiosroot.sh pipeline with PRA paths and an explicit
# capacity check against the real userdata partition.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ${EUID} != 0 ]]; then
    echo "run as root: iOS UID/GID values are part of the boot contract" >&2
    exit 2
fi

os=research/ipsw-x/087-86698-044.dmg
sysos=research/ipsw-x/087-86593-047.dmg
appos=research/ipsw-x/087-86715-047.dmg
out=research/iosroot/ios16-root.img
size=${1:-9.2G}

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
if (( want_kib >= userdata_kib )); then
    echo "error: $size does not leave room in the ${userdata_kib} KiB userdata partition" >&2
    exit 1
fi
echo "image $size (${want_kib} KiB), userdata ${userdata_kib} KiB"

tools/mkiosroot.sh "$os" "$sysos" "$appos" "$out" "$size"
ls -l "$out"
echo "stage with: tools/pra-stage-iosroot.sh $out"

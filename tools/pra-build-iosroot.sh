#!/bin/bash
# Build the iPhone X (d22ap) iOS 16.7.16 HFS+ root image on the PC.
#
#   sudo tools/pra-build-iosroot.sh [--full] [--force] [SIZE]
#
# Needs the three DMGs fetched by tools/pra-fetch-ipsw.sh, apfs-fuse and
# hfsprogs.
#
#   (default)  research/iosroot/ios16-root.img        trimmed, SIZE 9796M
#              that is the userdata partition (p58, 14340096 KiB = 14 GiB
#              after the GPT resize, research/gpt/geometry.env); mkiosroot.sh
#              drops only data no first-boot UI loads, so Setup.app, the
#              setup panes and the staged apps stay.
#   --full     research/iosroot/ios16-root-full.img   complete payload, SIZE 12G
#              keeps every file; needs a bigger partition than stock userdata,
#              so it is for a future GPT resize, not for staging today.
#
# The two builds never overwrite each other and both are kept. --force
# discards an existing image (and detaches its stale loop mount, which is what
# an interrupted earlier run leaves behind).
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
force=0
while [[ ${1:-} == --* ]]; do
    case $1 in
        --full) full=1 ;;
        --force) force=1 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
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

# An interrupted run leaves the image loop-mounted; the loop keeps the old
# inode alive and the next truncate would write a different file underneath it.
while IFS= read -r line; do
    ld=${line%%:*}
    backing=$(printf '%s' "$line" | sed -n 's/.*(\(.*\))$/\1/p')
    [[ $backing == */research/iosroot/*.img ]] || continue
    while IFS= read -r mp; do
        [[ -n $mp ]] && umount "$mp" 2>/dev/null
    done < <(awk -v d="$ld" '$1==d {print $2}' /proc/mounts)
    losetup -d "$ld" 2>/dev/null && echo "detached stale $ld ($backing)"
done < <(losetup -a 2>/dev/null)

if [[ -e $out ]]; then
    if (( force )); then
        rm -f "$out"
        echo "removed previous $out"
    else
        echo "refusing to overwrite $out (pass --force to rebuild)" >&2
        exit 1
    fi
fi

# p58 userdata size, read from the GPT-resize geometry so it cannot drift:
# stock was 10715136 first LBA + 10031104 KiB; after the resize (research/gpt/
# geometry.env) it is first LBA 2097152 + 14340096 KiB.
geometry=${geometry:-$(dirname "$0")/../research/gpt/geometry.env}
if [[ -r $geometry ]]; then
    # shellcheck disable=SC1090
    source "$geometry"
    userdata_kib=${USERDATA_KIB:?geometry.env lacks USERDATA_KIB}
else
    echo "warning: $geometry unreadable, assuming the post-resize 14340096 KiB" >&2
    userdata_kib=14340096
fi
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

# Donor finish steps (ios-galaxy-s8 tools/dreamlte/finish-iosroot.sh): the
# root tweaks that turned mkiosroot output into the donor's v8-v14 images
# that reached the home screen. Without them: launchd keeps spawning the
# churner jobs forever (the job database is System/Library/xpc/launchd.plist,
# NOT the LaunchDaemons files mkiosroot removes), /private/var/containers is
# missing, the purplebuddy Setup bypass never engages (Setup runs its
# wizard), SpringBoard has no BKNoWatchdogs, mediaserverd crash-loops.
# Idempotent; this script runs as root, so mount - tweak - umount here.
mnt=$(mktemp -d)
fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
mount -t hfsplus -o loop,force "$out" "$mnt"
python3 "$(dirname "$0")/sweet-root-tweaks.py" "$mnt"
sync
umount "$mnt"
rmdir "$mnt"
fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
fsck.hfsplus -f -n "$out"

ls -l "$out"
echo "stage with: tools/pra-stage-iosroot.sh $out"

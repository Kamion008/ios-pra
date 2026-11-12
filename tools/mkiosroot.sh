#!/bin/bash
# Build the SWEET iOS root: one case-sensitive HFS+ image holding an iOS OS
# root filesystem plus its cryptexes, for the userdata partition (rd=ufsroot0).
#
#   mkiosroot.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]     (SIZE default 16G)
#
# MKROOT_TRIM=0 builds the complete payload (11.66 GB, does not fit the
# 9.57 GiB userdata partition); the default MKROOT_TRIM=1 drops the payload
# nothing on the boot path loads so the image fits (see the list below).
#
# The IPSW images are raw APFS with LZBITMAP-compressed files: they are read
# through apfs-fuse (decompressing), so the HFS+ copy is uncompressed. On a
# device /private/preboot is its own volume holding the cryptexes, which
# /System/Cryptexes/{OS,App} link to; here they live inside the one volume.
# Owners, modes, symlinks and hard links are preserved (rsync -aH as root).
#
# The volume is journaled (XNU replays the journal after a panic; Linux only
# mounts it read-write with -o force and leaves the journal empty). SWEET
# additions: /System/Library/Caches/com.apple.dyld hard-links the SystemOS
# cryptex shared cache (ignition_level=1 looks there), and
# /private/var/keybags/systembag.kb is the plain-plist system keybag that
# keybagd reads with /defaults/no-effaceable-storage (tools/mkadt.py).
set -euo pipefail

[[ $# -ge 4 ]] || { sed -n '2,12p' "$0"; exit 2; }
os=$(realpath "$1") sysos=$(realpath "$2") appos=$(realpath "$3") out=$4 size=${5:-16G}
trim=${MKROOT_TRIM:-1}
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }

# Pre-flight tool check
missing_tools=()
for tool in apfs-fuse mkfs.hfsplus rsync; do
	command -v "$tool" >/dev/null 2>&1 || missing_tools+=("$tool")
done

if [[ ${#missing_tools[@]} -gt 0 ]]; then
	echo "Error: missing required host utilities: ${missing_tools[*]}" >&2
	echo "  Install instructions:" >&2
	echo "    Arch Linux:    sudo pacman -S apfs-fuse hfsprogs rsync" >&2
	echo "    Ubuntu/Debian: sudo apt install apfs-fuse hfsprogs rsync" >&2
	echo "    Fedora:        sudo dnf install apfs-fuse hfsplus-tools rsync" >&2
	exit 1
fi

work=$(mktemp -d)
mounts=()
cleanup() {
	local busy=0
	for m in "${mounts[@]}"; do
		if mountpoint -q "$m"; then
			sudo umount "$m" 2>/dev/null || true
		fi
		mountpoint -q "$m" && busy=1
	done
	# Never recurse into a directory that is still mounted (the root is writable).
	if [[ $busy == 0 ]]; then
		rm -f "$work"/*.dmg
		rmdir "$work"/* "$work" 2>/dev/null || true
	else
		echo "still mounted under $work: left in place" >&2
	fi
}
mon=
trap '[[ -n $mon ]] && kill "$mon" 2>/dev/null; cleanup' EXIT

say() { printf '\n=== [%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# rsync prints nothing for twenty minutes, so sample the mounted image and
# report how much of the expected payload has landed, with a rate and ETA.
# The total is a rough figure (du -sb of the DMGs minus the trim list); the
# final df -h below is the authoritative number.
monitor() {
	local last=0 used delta eta
	while :; do
		sleep 15 || return 0
		used=$(df -B1 --output=used "$work/root" 2>/dev/null | tail -1 | tr -d ' ')
		[[ -n ${used:-} ]] || continue
		used=$((used / 1048576))
		delta=$((used - last)); last=$used
		if (( delta > 0 )); then
			eta=$(( (payload_mib - used) * 15 / delta / 60 ))
			(( eta < 0 )) && eta=0
			printf '  ... %5d / ~%d MiB (%3d%%), %d MiB/min, eta ~%d min\n' \
				"$used" "$payload_mib" $((used * 100 / payload_mib)) $((delta * 4)) "$eta"
		else
			printf '  ... %5d / ~%d MiB\n' "$used" "$payload_mib"
		fi
	done
}

# apfs-fuse splits its options on ',' (e.g. in iPhone10,3 paths): use links.
# Keep the .dmg name: apfs-fuse only parses UDIF images (the OS one is UDIF,
# the cryptexes are raw APFS) when the file name ends in .dmg.
apfs_mount() {
	ln -s "$1" "$work/$2.dmg"
	mkdir "$work/$2"
	# As root: a user's FUSE mount is unreadable to the root rsync below.
	sudo "$(command -v apfs-fuse)" "$work/$2.dmg" "$work/$2"
	mounts+=("$work/$2")
}
apfs_mount "$os" os
apfs_mount "$sysos" sysos
apfs_mount "$appos" appos

say "formatting $size case-sensitive journaled HFS+"
truncate -s "$size" "$out"
mkfs.hfsplus -s -J -v iOSRoot "$out"
mkdir "$work/root"
say "mounting $out on $work/root"
sudo mount -t hfsplus -o loop,force "$out" "$work/root"
mounts=("$work/root" "${mounts[@]}")
payload_mib=$(( trim == 1 ? 8656 : 11894 ))
monitor & mon=$!

# Linux has no way to set a symlink's mode (fchmodat with AT_SYMLINK_NOFOLLOW
# returns EOPNOTSUPP), so rsync reports one "failed to set permissions" per
# symlink and exits 23. Symlink modes carry no meaning on HFS+ or to XNU, so
# those are filtered, but only after checking that every failing path really is
# a symlink in the destination and that rsync said nothing else.
copy() {
	say "copying $1 -> ${2#"$work/root"}"
	sudo mkdir -p "$2"
	local err="$work/rsync.err" rc=0 perm other
	sudo rsync -aH --numeric-ids "${extra_excludes[@]}" "$1/" "$2/" 2>"$err" || rc=$?
	perm=$(grep -c 'failed to set permissions on .*Operation not supported (95)' "$err" 2>/dev/null || true)
	other=$(grep -v -e 'failed to set permissions on .*Operation not supported (95)' \
		-e '^rsync error: some files/attrs were not transferred' "$err" 2>/dev/null | grep -c . || true)
	if (( other > 0 )); then
		cat "$err" >&2
		echo "error: rsync reported $other unexpected messages" >&2
		exit 1
	fi
	if (( perm > 0 )); then
		local matched notlink
		matched=$(sed -n 's/.*failed to set permissions on "\(.*\)": Operation not supported (95)$/\1/p' "$err" | wc -l)
		if (( matched != perm )); then
			cat "$err" >&2
			echo "error: could not account for every rsync chmod failure" >&2
			exit 1
		fi
		notlink=$(sed -n 's/.*failed to set permissions on "\(.*\)": Operation not supported (95)$/\1/p' "$err" |
			sudo xargs -r -d '\n' sh -c 'for p; do [ -L "$p" ] || printf "%s\n" "$p"; done' sh)
		if [[ -n $notlink ]]; then
			echo "error: chmod failed on paths that are not symlinks:" >&2
			printf '%s\n' "$notlink" | head -20 >&2
			exit 1
		fi
		echo "  ($perm symlink chmod warnings ignored; rsync cannot set symlink modes on Linux)"
	fi
	if (( rc != 0 && rc != 23 )); then
		echo "error: rsync exited $rc" >&2
		exit 1
	fi
}

# The complete root is 11.66 GB and the userdata partition is 9.57 GiB, so the
# default build drops payload that nothing on the boot path loads. Sizes
# measured on the 16.7.16 d22ap images with du -sb. MKROOT_TRIM=0 keeps
# everything (the image then needs a bigger partition than stock userdata).
if [[ $trim == 1 ]]; then
	# Everything Setup.app, OnBoardingBundles, the first-boot installd pass
	# (/private/var/staged_system_apps), Siri, Health, VoiceOver and the
	# English/Italian dictation bundles need is kept: only data that no
	# first-boot UI loads is dropped.
	extra_excludes=(
		--exclude='/System/Library/PreinstalledAssetsV2'  # 692 MB, preinstalled voice/Siri/AirDrop/geo assets
		--include='/System/Library/LinguisticData/'
		--include='/System/Library/LinguisticData/RequiredAssets_en.bundle/***'
		--include='/System/Library/LinguisticData/RequiredAssets_it.bundle/***'
		--exclude='/System/Library/LinguisticData/***'    # ~880 MB, the other 59 dictation languages
		--exclude='/usr/standalone/update'                # 170 MB, restore/update payloads
		--exclude='/System/Library/NanoTimeKit'           # 139 MB, watch faces
		--exclude='/usr/share/tokenizer'                  # 57 MB, CJK keyboard dictionaries
	)
else
	extra_excludes=()
fi
copy "$work/os/root" "$work/root"
if [[ $trim == 1 ]]; then
	# The SystemOS cryptex carries dyld's .symbols file (592 MB): dyld never
	# maps it, it is only for offline symbolication of a shared cache.
	extra_excludes+=(--exclude='*.symbols' --exclude='*.symbols.*')
fi
copy "$work/sysos/root" "$work/root/private/preboot/Cryptexes/OS"
extra_excludes=()
copy "$work/appos/root" "$work/root/private/preboot/Cryptexes/App"

# Shared cache where dyld looks at ignition level 1: hard links, no extra space.
dsc=private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld
sudo mkdir -p "$work/root/System/Library/Caches/com.apple.dyld"
say "hard-linking the shared cache into /System/Library/Caches"
for f in "$work/root/$dsc"/*; do
	sudo ln "$f" "$work/root/System/Library/Caches/com.apple.dyld/${f##*/}"
done

# dyld does not search the cryptexes at ignition level 1: hard-link every
# cryptex file that has no counterpart in the OS root (libobjc-trampolines,
# libffi-trampolines, libstdc++, ...) to its root path.
say "hard-linking cryptex-only files into the root"
for c in OS App; do
	(cd "$work/root/private/preboot/Cryptexes/$c" && sudo find . ! -type d ! -path './System/Library/Caches/com.apple.dyld/*') |
	while IFS= read -r f; do
		f=${f#./}
		if ! sudo test -e "$work/root/$f" && ! sudo test -L "$work/root/$f"; then
			sudo mkdir -p "$work/root/$(dirname "$f")"
			src="$work/root/private/preboot/Cryptexes/$c/$f"
			# Linux hfsplus cannot hard-link symlinks: copy those.
			if sudo test -L "$src"; then sudo cp -P "$src" "$work/root/$f"; else sudo ln "$src" "$work/root/$f"; fi
			echo "linked $c:/$f"
		fi
	done
done

# logd's log stores, normally made at restore: it checks owner _logd (272)
# and mode, plus a .migrated marker, else asks a helper and crashes
# ("BUG IN LIBTRACE: Failed to migrate directory").
say "creating logd stores and the system keybag"
db="$work/root/private/var/db"
sudo install -d -o 272 -g 272 -m 0751 "$db/diagnostics"
sudo install -d -o 272 -g 272 -m 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for d in diagnostics uuidtext diagnostics/timesync; do
	sudo install -o 272 -g 272 -m 0644 /dev/null "$db/$d/.migrated"
done

# System keybag for the built-in AppleKeyStore (no passcode).
sudo install -d -m 0700 -o 0 -g 0 "$work/root/private/var/keybags"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
	'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
	'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>' |
	sudo install -m 0600 -o 0 -g 0 /dev/stdin "$work/root/private/var/keybags/systembag.kb"

say "copy finished; free space"
df -h "$work/root"
avail=$(df -B1 --output=avail "$work/root" | tail -1)
if (( avail < 200 * 1024 * 1024 )); then
	echo "error: only $((avail / 1048576)) MiB left in the image for /private/var" >&2
	exit 1
fi
echo "free space in the image: $((avail / 1048576)) MiB"
say "unmounting and verifying with fsck"
sudo umount "$work/root"
# Linux hfsplus decomposes some non-ASCII names (localized Shortcuts examples)
# differently from Apple's tables; let fsck_hfs rewrite them, then verify.
fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
fsck.hfsplus -f -n "$out"

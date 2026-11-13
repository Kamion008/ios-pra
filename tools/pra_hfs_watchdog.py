#!/usr/bin/env python3
"""Set FBLaunchWatchdogExceptions in an HFSX image of the PRA iOS root.

The SpringBoard preference file is one allocation block with ~2 KiB of
unused tail, so the new plist is re-encoded to *exactly* the old logical
size.  That keeps the data fork length unchanged: no catalog record, no
B-tree node and no allocation bitmap is touched - only the file's own
data bytes are rewritten.  A filler key absorbs the size difference.

  pra_hfs_watchdog.py IMAGE --add com.apple.purplebuddy=280 [--dry-run]

Writes: the file's logical bytes, in place, at the only offset in the
image where the current plist content matches.  Prints the device LBAs
to write back with dd (--part-lba, default 10715136 = p58 userdata).

The journal is reported but not modified: if the volume was not
unmounted cleanly, XNU may replay the same block and undo the edit -
the ring log showing "20.00 seconds" instead of "300.00 seconds" is the
tell.  Replaying with fsck.hfsplus first is the cure.
"""
import argparse
import mmap
import os
import plistlib
import struct
import sys

BLOCK = 4096
PAD_KEY = "PRAWatchdogPad"
TARGET_FILE = "com.apple.springboard.plist"
NEEDLE_OFF = 600
NEEDLE_LEN = 100


def find_file(img, content):
    """Return the image offset of the file's first byte, or None."""
    needle = content[NEEDLE_OFF:NEEDLE_OFF + NEEDLE_LEN]
    if len(needle) < NEEDLE_LEN:
        needle = content[:min(64, len(content))]
    hits = []
    with open(img, "rb", buffering=0) as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            i = m.find(needle)
            while i >= 0:
                base = i - NEEDLE_OFF
                if base >= 0 and m[base:base + len(content)] == content:
                    hits.append(base)
                    if len(hits) > 4:
                        break
                i = m.find(needle, i + 1)
    return hits


def build_plist(old_bytes, additions):
    d = plistlib.loads(old_bytes)
    for k, v in additions.items():
        d[k] = v
    exact = plistlib.dumps(d, fmt=plistlib.FMT_BINARY, sort_keys=True)
    if len(exact) == len(old_bytes):
        return exact, None
    if len(exact) > len(old_bytes):
        raise SystemExit(
            "re-encoded plist is %d bytes, %d too big for the %d-byte file"
            % (len(exact), len(exact) - len(old_bytes), len(old_bytes)))
    pad = pad_len = 0
    for n in range(0, len(old_bytes) - len(exact) + 16):
        probe = dict(d)
        probe[PAD_KEY] = "x" * n
        b = plistlib.dumps(probe, fmt=plistlib.FMT_BINARY, sort_keys=True)
        if len(b) == len(old_bytes):
            pad, pad_len = b, n
            break
    if not pad:
        raise SystemExit("cannot pad the plist to exactly %d bytes"
                         % len(old_bytes))
    return pad, pad_len


def journal_state(img):
    with open(img, "rb", buffering=0) as f:
        f.seek(1024)
        vh = f.read(512)
        attrs, = struct.unpack_from(">I", vh, 4)
        if not attrs & (1 << 13):
            return "not journaled"
        jib, = struct.unpack_from(">I", vh, 12)
        f.seek(jib * BLOCK)
        b = f.read(512)
        flags, = struct.unpack_from(">I", b, 0)
        off, size = struct.unpack_from(">QQ", b, 36)
        if not flags & 1:
            return "journal on another device (flags=0x%x)" % flags
        f.seek(off)
        h = f.read(64)
        magic, = struct.unpack_from("<I", h, 0)
        fmt = "<" if magic == 0x4A4E4C78 else ">"
        start, end, size = struct.unpack_from(fmt + "QQQ", h, 8)
        if start == end:
            return "in-FS journal offset=%d size=%d %s empty (clean)" % (
                off, size, "LE" if fmt == "<" else "BE")
        return ("in-FS journal offset=%d size=%d %s PENDING %d..%d (%d bytes); "
                "replay may undo this edit if the block is in there"
                % (off, size, "LE" if fmt == "<" else "BE", start, end,
                   end - start))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--add", action="append", required=True,
                    metavar="BUNDLE_ID=SECONDS",
                    help="watchdog exception, additive seconds (20 s base)")
    ap.add_argument("--part-lba", type=int, default=10715136,
                    help="first LBA of the partition in the image (p58)")
    ap.add_argument("--plist", help="current plist file (default: read it "
                    "from the read-only mount at /tmp/opencode/p58ro)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    additions = {}
    for a in args.add:
        k, v = a.split("=", 1)
        additions.setdefault("FBLaunchWatchdogExceptions", {})[k] = float(v)

    print("image: %s (%.2f GiB)" % (args.image, os.path.getsize(args.image) / 2**30))
    print("journal: %s" % journal_state(args.image))

    path = args.plist or os.path.join(
        "/tmp/opencode/p58ro",
        "private/var/mobile/Library/Preferences", TARGET_FILE)
    if os.path.exists(path):
        old = open(path, "rb").read()
        print("plist from mounted image: %d bytes" % len(old))
    else:
        raise SystemExit("%s not found; mount the image read-only at "
                         "/tmp/opencode/p58ro first" % path)

    new, pad_len = build_plist(old, additions)
    print("new plist: %d bytes (pad key %d chars), keys=%s"
          % (len(new), pad_len if pad_len is not None else -1,
             {k: v for k, v in additions.items()}))

    hits = find_file(args.image, old)
    if len(hits) != 1:
        raise SystemExit("expected exactly one copy of the plist in the image, "
                         "found %r" % hits)
    off = hits[0]
    if off % BLOCK + len(new) > BLOCK:
        raise SystemExit("plist spans a block boundary at %d; refusing" % off)
    blk, inblk = divmod(off, BLOCK)
    print("content at image offset %d, block %d +%d (block-aligned=%s)"
          % (off, blk, inblk, inblk == 0))
    print("device LBA for dd: %d (block %d of partition at LBA %d)"
          % (args.part_lba + off // 512, blk, args.part_lba))

    if args.dry_run:
        print("dry run: nothing written")
        return

    with open(args.image, "r+b", buffering=0) as f:
        f.seek(off)
        f.write(new)
        f.seek(off)
        back = f.read(len(new))
    if back != new:
        raise SystemExit("read-back mismatch")
    d = plistlib.loads(back)
    got = d.get("FBLaunchWatchdogExceptions")
    print("verified: FBLaunchWatchdogExceptions=%r keys=%d" % (got, len(d)))

    out = "/tmp/opencode/plist_block.bin"
    with open(args.image, "rb", buffering=0) as f:
        f.seek(blk * BLOCK)
        whole = f.read(BLOCK)
    open(out, "wb").write(whole)
    print("block payload: %s (%d bytes)" % (out, len(whole)))
    print("apply from TWRP:")
    print("  adb push %s /tmp/plist_block.bin && adb shell "
          "'dd if=/tmp/plist_block.bin of=/dev/block/mmcblk0 bs=4096 seek=%d'"
          % (out, (args.part_lba * 512 + blk * BLOCK) // BLOCK))


if __name__ == "__main__":
    main()

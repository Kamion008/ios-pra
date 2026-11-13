#!/usr/bin/env python3
"""Report or clear the HFS+ journal flag on the PRA iOS root.

The journal doubles every metadata write (journal copy, then the home
location) and the p58 volume only writes at ~600 KiB/s, so an unjournaled
mount is the cheapest write-side experiment we have.  The flag lives in
the volume header attributes word (bit 13, kHFSVolumeJournaledBit), so
turning it off is a two-byte change - no catalog, no B-tree, no bitmap.

  pra_hfs_journal.py IMAGE --report
  pra_hfs_journal.py IMAGE --clear [--dry-run] [--force]

Both the primary (offset 1024) and the alternate (last 1024 bytes of the
partition) volume headers are edited: fsck.hfsplus compares them and
complains when they disagree.  Each edited 512-byte sector is saved to
/tmp/opencode/ before the write, and the dd lines for the device are
printed.  Clearing the bit while the journal still holds transactions
loses them, so --clear refuses unless the journal is empty or --force is
given; run fsck.hfsplus -f -y on a dump first if you want it replayed.
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys

SECTOR = 512
VH_OFF = 1024
JOURNALED = 1 << 13          # kHFSVolumeJournaledBit, attr word offset 4
BLOCK = 4096
SAVE_DIR = "/tmp/opencode"


def read_at(f, off, n):
    f.seek(off)
    return f.read(n)


def parse_vh(b, where):
    """Decode the fields we care about out of one 512-byte volume header."""
    if len(b) < 512:
        return None
    sig = struct.unpack_from(">H", b, 0)[0]
    attrs, = struct.unpack_from(">I", b, 4)
    jib, = struct.unpack_from(">I", b, 12)
    create = struct.unpack_from(">I", b, 20)[0]
    blksz, = struct.unpack_from(">I", b, 40)
    return {
        "where": where,
        "sig": sig,
        "attrs": attrs,
        "journaled": bool(attrs & JOURNALED),
        "journal_info_block": jib,
        "create_date": create,
        "blocksize": blksz,
    }


def describe_sig(sig):
    return {0x4244: "HFS (BD)", 0x482B: "HFS+ (H+)",
            0x4858: "HFSX (HX)"}.get(sig, "unknown 0x%04x" % sig)


def journal_header(img, jib):
    """Return (offset, size, start, end, endian) for the in-FS journal."""
    with open(img, "rb", buffering=0) as f:
        b = read_at(f, jib * BLOCK, SECTOR)
        if len(b) < SECTOR:
            return None
        flags, = struct.unpack_from(">I", b, 0)
        off, size = struct.unpack_from(">QQ", b, 36)
        if not flags & 1:
            return ("external", off, size, None, None, None)
        f.seek(off)
        h = f.read(64)
        if len(h) < 64:
            return None
        magic, = struct.unpack_from("<I", h, 0)
        fmt = "<" if magic == 0x4A4E4C78 else ">"
        start, end, jsize = struct.unpack_from(fmt + "QQQ", h, 8)
        if jsize == 0 or jsize > size:
            # A freshly formatted Linux volume can carry a blank journal
            # header; the real size is in the journal info block.
            jsize = size
        return ("inline", off, jsize, start, end,
                "LE" if fmt == "<" else "BE")


def show_state(img, part_lba, part_sectors):
    size = os.path.getsize(img)
    with open(img, "rb") as f:
        prim = parse_vh(read_at(f, VH_OFF, SECTOR), "primary")
        alt_off = part_sectors * SECTOR - 1024 if part_sectors else None
        alt = None
        if alt_off is not None and alt_off + SECTOR <= size:
            alt = parse_vh(read_at(f, alt_off, SECTOR), "alternate")
    print("image: %s (%.2f GiB, %d bytes)"
          % (img, size / 2**30, size))
    for v in (prim, alt):
        if not v:
            print("volume header: %s missing" % ("alternate" if prim else "primary"))
            continue
        print("%-9s volume header at %8d: %s attrs=0x%08x journaled=%s "
              "journal_info_block=%d block=%d"
              % (v["where"], alt_off if v["where"] == "alternate" else VH_OFF,
                 describe_sig(v["sig"]), v["attrs"],
                 "YES" if v["journaled"] else "no",
                 v["journal_info_block"], v["blocksize"]))
    if prim and prim["journaled"]:
        jh = journal_header(img, prim["journal_info_block"])
        if jh is None:
            print("journal: unreadable")
        elif jh[0] == "external":
            print("journal: on another device (flags say external), "
                  "offset=%d size=%d" % (jh[1], jh[2]))
        else:
            _, off, jsize, start, end, endian = jh
            if start == end:
                print("journal: inline offset=%d size=%d %s empty (clean)"
                      % (off, jsize, endian))
            else:
                print("journal: inline offset=%d size=%d %s PENDING "
                      "%d..%d (%d bytes) - replay will touch that range"
                      % (off, jsize, endian, start, end, end - start))
    return prim, alt, alt_off


def fsck(img, fix):
    if not shutil.which("fsck.hfsplus"):
        return "fsck.hfsplus not installed"
    cmd = ["fsck.hfsplus", "-f"] + (["-y"] if fix else ["-n"]) + [img]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip().splitlines()
    tail = out[-1] if out else "(no output)"
    return "rc=%d %s" % (p.returncode, tail)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--report", action="store_true", help="only print state")
    ap.add_argument("--clear", action="store_true",
                    help="clear kHFSVolumeJournaledBit in both volume headers")
    ap.add_argument("--part-lba", type=int, default=10715136,
                    help="first LBA of the partition inside the image (p58)")
    ap.add_argument("--part-sectors", type=int, default=0,
                    help="partition length in 512-byte sectors, needed to find "
                         "the alternate volume header (p58: 20062208)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="clear the bit even though the journal is not empty")
    ap.add_argument("--skip-fsck", action="store_true")
    args = ap.parse_args()

    prim, alt, alt_off = show_state(args.image, args.part_lba,
                                    args.part_sectors)
    if not prim:
        raise SystemExit("no volume header at offset %d" % VH_OFF)
    if not args.clear:
        return
    if prim["sig"] not in (0x482B, 0x4858):
        raise SystemExit("signature 0x%04x is not HFS+/HFSX; refusing"
                         % prim["sig"])
    if alt and alt["sig"] != prim["sig"]:
        raise SystemExit("alternate volume header signature 0x%04x does not "
                         "match primary 0x%04x; refusing"
                         % (alt["sig"], prim["sig"]))
    if not prim["journaled"]:
        print("nothing to do: already not journaled")
        return

    if not args.skip_fsck:
        print("fsck before: %s" % fsck(args.image, fix=False))
        pend = False
        jh = journal_header(args.image, prim["journal_info_block"])
        if jh and jh[0] == "inline" and jh[3] != jh[4]:
            pend = True
        if pend and not args.force:
            raise SystemExit(
                "journal has pending transactions; clearing the bit would "
                "drop them. Run fsck.hfsplus -f -y on a dump first, then "
                "--clear, or pass --force to accept the loss")

    edits = []
    for where, off, vh in (("primary", VH_OFF, prim), ("alternate", alt_off, alt)):
        if vh is None:
            continue
        sec = (off // SECTOR) * SECTOR
        # Each header keeps its own unrelated attribute bits: the primary
        # normally has kHFSVolumeUnmountedBit (0x100) cleared because iOS was
        # running when the volume was last written, while the alternate still
        # has it set. Only bit 13 changes, in both.
        edits.append((where, sec, off - sec, vh["attrs"],
                      vh["attrs"] & ~JOURNALED))
    for where, sec, insec, old_attrs, new_attrs in edits:
        print("%-9s sector %d (offset %d, +%d): attrs 0x%08x -> 0x%08x"
              % (where, sec // SECTOR, sec, insec, old_attrs, new_attrs))

    if args.dry_run:
        print("dry run: nothing written")
        return

    os.makedirs(SAVE_DIR, exist_ok=True)
    payloads = []
    with open(args.image, "r+b", buffering=0) as f:
        for where, sec, insec, old_attrs, new_attrs in edits:
            f.seek(sec)
            orig = f.read(SECTOR)
            keep = os.path.join(SAVE_DIR, "journal_vh_%s.orig" % where)
            open(keep, "wb").write(orig)
            buf = bytearray(orig)
            struct.pack_into(">I", buf, insec + 4, new_attrs)
            f.seek(sec)
            f.write(bytes(buf))
            f.seek(sec)
            back = f.read(SECTOR)
            if back != bytes(buf):
                raise SystemExit("%s read-back mismatch" % where)
            out = os.path.join(SAVE_DIR, "journal_vh_%s.bin" % where)
            open(out, "wb").write(bytes(buf))
            payloads.append((where, out, sec))
            print("%-9s written, saved original to %s" % (where, keep))
            print("%-9s readback attrs=0x%08x journaled=%s"
                  % (where, struct.unpack_from(">I", back, insec + 4)[0],
                     "YES" if struct.unpack_from(">I", back, insec + 4)[0]
                     & JOURNALED else "no"))

    if not args.skip_fsck:
        print("fsck after:  %s" % fsck(args.image, fix=False))

    print("apply from TWRP (partition base LBA %d):" % args.part_lba)
    for where, out, sec in payloads:
        dev_lba = args.part_lba + sec // SECTOR
        print("  adb push %s /tmp/journal_vh_%s.bin && adb shell "
              "'dd if=/tmp/journal_vh_%s.bin of=/dev/block/mmcblk0 "
              "bs=512 seek=%d count=1'" % (out, where, where, dev_lba))
    print("revert: same dd with /tmp/opencode/journal_vh_*.orig")


if __name__ == "__main__":
    main()

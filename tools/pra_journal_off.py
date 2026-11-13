#!/usr/bin/env python3
"""Clear the HFS+ journal bit on the phone's p58 root, two sectors at a time.

The image-side tool (pra_hfs_journal.py) needs a 9.8 GiB dump to edit a
volume header that is 512 bytes.  This does the same job over adb from
TWRP: read the four sectors that matter (both volume headers, the journal
info block, the journal header), refuse if the journal still holds
transactions unless --force, flip bit 13 in both headers, write them back
and read them back again.

  pra_journal_off.py --report            # fetch and print, write nothing
  pra_journal_off.py --off [--force]     # flip the bit, keep the originals
  pra_journal_off.py --restore           # write back the saved originals

The drive of every edit is saved as /tmp/opencode/vh_<name>.orig and the
device location is printed, so --restore works even after a reboot of this
PC as long as /tmp survives; otherwise re-read the sectors and patch by
hand (attrs word is big-endian at offset 4 of each 512-byte header,
primary at image offset 1024, alternate at part_size - 1024).
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys

SECTOR = 512
DEFAULT_SERIAL = "57U7N17912003349"
PART_LBA = 10715136
PART_SECTORS = 20062208
JOURNALED = 1 << 13
SAVE_DIR = "/tmp/opencode"


def adb(serial, *args, binary=False):
    cmd = ["adb", "-s", serial] + list(args)
    p = subprocess.run(cmd, capture_output=True, text=not binary)
    if p.returncode != 0:
        raise SystemExit("adb %s failed: %s" %
                         (" ".join(args), (p.stderr or b"").decode(
                             errors="replace") if binary else p.stderr))
    return p.stdout


def read_sector(serial, lba):
    out = adb(serial, "exec-out",
              "dd if=/dev/block/mmcblk0 bs=512 skip=%d count=1 2>/dev/null"
              % lba, binary=True)
    if len(out) != SECTOR:
        raise SystemExit("short read at LBA %d: %d bytes" % (lba, len(out)))
    return out


def write_sector(serial, lba, data):
    tmp = "/tmp/pra_vh.bin"
    open("/tmp/opencode/.pra_vh_up.bin", "wb").write(data)
    adb(serial, "push", "/tmp/opencode/.pra_vh_up.bin", tmp)
    adb(serial, "shell",
        "dd if=%s of=/dev/block/mmcblk0 bs=512 seek=%d count=1 2>/dev/null"
        % (tmp, lba))
    back = read_sector(serial, lba)
    if back != data:
        raise SystemExit("read-back mismatch at LBA %d" % lba)
    return back


def attrs_of(b):
    return struct.unpack_from(">I", b, 4)[0]


def set_attrs(b, value):
    buf = bytearray(b)
    struct.pack_into(">I", buf, 4, value)
    return bytes(buf)


def describe(b, name, lba):
    sig = struct.unpack_from(">H", b, 0)[0]
    a = attrs_of(b)
    print("%-9s LBA %-9d sig=%s attrs=0x%08x journaled=%s unmounted=%s"
          % (name, lba, {0x4244: "HFS", 0x482B: "HFS+",
                         0x4858: "HFSX"}.get(sig, "0x%04x" % sig),
             a, "YES" if a & JOURNALED else "no",
             "yes" if a & 0x100 else "no"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default=os.environ.get("PRA_SERIAL",
                                                       DEFAULT_SERIAL))
    ap.add_argument("--report", action="store_true", help="print state only")
    ap.add_argument("--off", action="store_true", help="clear the journal bit")
    ap.add_argument("--restore", action="store_true",
                    help="write the saved originals back")
    ap.add_argument("--force", action="store_true",
                    help="clear even if the journal holds transactions")
    args = ap.parse_args()
    if not (args.report or args.off or args.restore):
        ap.error("one of --report/--off/--restore is required")

    S = args.serial
    primary_lba = PART_LBA + 1024 // SECTOR
    alt_off = PART_SECTORS * SECTOR - 1024
    alternate_lba = PART_LBA + alt_off // SECTOR

    prim = read_sector(S, primary_lba)
    jib_blk, = struct.unpack_from(">I", prim, 12)
    jib_lba = PART_LBA + jib_blk * 8            # 4 KiB block, 512 B sectors
    jib = read_sector(S, jib_lba)
    alt = read_sector(S, alternate_lba)

    describe(prim, "primary", primary_lba)
    describe(alt, "alternate", alternate_lba)
    flags, = struct.unpack_from(">I", jib, 0)
    joff, jsize = struct.unpack_from(">QQ", jib, 36)
    pending = None
    if flags & 1 and joff:
        jh = read_sector(S, PART_LBA + joff // SECTOR)
        magic, = struct.unpack_from("<I", jh, 0)
        fmt = "<" if magic == 0x4A4E4C78 else ">"
        start, end, jlen = struct.unpack_from(fmt + "QQQ", jh, 8)
        pending = (start, end)
        print("journal: inline offset=%d size=%d %s %s"
              % (joff, jlen or jsize, "LE" if fmt == "<" else "BE",
                 "empty (clean)" if start == end else
                 "PENDING %d..%d (%d bytes)" % (start, end, end - start)))
    else:
        print("journal: external (flags=0x%x) or absent" % flags)

    if args.report:
        return

    if args.restore:
        os.makedirs(SAVE_DIR, exist_ok=True)
        for name, lba in (("primary", primary_lba),
                          ("alternate", alternate_lba)):
            p = os.path.join(SAVE_DIR, "vh_%s.orig" % name)
            if not os.path.exists(p):
                raise SystemExit("%s missing; cannot restore" % p)
            data = open(p, "rb").read()
            write_sector(S, lba, data)
            describe(data, name, lba)
            print("%-9s restored" % name)
        return

    if not attrs_of(prim) & JOURNALED and not attrs_of(alt) & JOURNALED:
        print("nothing to do: neither header is journaled")
        return
    if pending and pending[0] != pending[1] and not args.force:
        raise SystemExit(
            "journal has %d bytes pending; clearing the bit would discard "
            "them. Boot once and let XNU replay, or pass --force"
            % (pending[1] - pending[0]))

    os.makedirs(SAVE_DIR, exist_ok=True)
    for name, lba, blob in (("primary", primary_lba, prim),
                            ("alternate", alternate_lba, alt)):
        open(os.path.join(SAVE_DIR, "vh_%s.orig" % name), "wb").write(blob)
        old = attrs_of(blob)
        new_blob = set_attrs(blob, old & ~JOURNALED)
        write_sector(S, lba, new_blob)
        print("%-9s 0x%08x -> 0x%08x, written and read back at LBA %d "
              "(original saved)" % (name, old, attrs_of(new_blob), lba))

    print("verify with: pra_journal_off.py --report  (expect journaled=no)")
    print("revert with: pra_journal_off.py --restore")


if __name__ == "__main__":
    main()

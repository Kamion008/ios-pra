#!/usr/bin/env python3
"""Build a new GPT for PRA-LX1 that grows `userdata` over the Android-only
partitions, so the iOS HFS+ root fits on internal eMMC.

The layout is emitted as two raw blobs:

  gpt-primary.bin   33 sectors, written at LBA 1
  gpt-backup.bin    33 sectors, written at total_sectors-33 (only with
                    --layout std; Huawei ships last_usable = total-1)

Nothing is written to a device here; this only produces bytes and prints the
resulting table so it can be reviewed before anyone dd's it.

Usage:
  pra-gpt-resize.py --disk dump/mmcblk0.bin --out research/gpt \
      --drop preas preavs system cust version vendor product

Defaults match the PRA-LX1 Android layout; `userdata` is always the extended
partition.
"""
import argparse
import hashlib
import os
import struct
import sys
import zlib

SECTOR = 512
ENTRY_SIZE = 128
ENTRIES = 128

DROP_DEFAULT = ["preas", "preavs", "system", "cust", "version", "vendor", "product"]


def gpt_crc(data):
    return zlib.crc32(data) & 0xFFFFFFFF


class GPT:
    def __init__(self, disk_path):
        with open(disk_path, "rb") as f:
            f.seek(SECTOR)
            self.hdr = bytearray(f.read(92))
            (
                self.sig,
                self.rev,
                self.hdr_size,
                self.hdr_crc,
                _res,
                self.current_lba,
                self.backup_lba,
                self.first_usable,
                self.last_usable,
                self.disk_guid,
            ) = struct.unpack("<8sIIIIQQQQ16s", bytes(self.hdr[:72]))
            self.entries_lba, self.n_entries, self.entry_size, self.entries_crc = struct.unpack(
                "<QIII", bytes(self.hdr[72:92])
            )
            assert self.sig == b"EFI PART", "no primary GPT at LBA 1"
            assert self.entry_size == ENTRY_SIZE and self.n_entries == ENTRIES
            body = bytearray(self.hdr)
            body[16:20] = b"\0\0\0\0"
            assert gpt_crc(bytes(body)) == self.hdr_crc, "primary GPT header CRC mismatch"

            f.seek(self.entries_lba * SECTOR)
            self.entries = bytearray(f.read(self.n_entries * self.entry_size))
            assert gpt_crc(bytes(self.entries)) == self.entries_crc, "entry array CRC mismatch"

    def partitions(self):
        out = []
        for i in range(self.n_entries):
            e = self.entries[i * ENTRY_SIZE:(i + 1) * ENTRY_SIZE]
            if e[:16] == b"\0" * 16:
                continue
            first, last = struct.unpack_from("<QQ", e, 32)
            name = e[56:128].decode("utf-16-le").rstrip("\0")
            out.append(
                {
                    "index": i + 1,
                    "name": name,
                    "first": first,
                    "last": last,
                    "entry": i * ENTRY_SIZE,
                }
            )
        return out

    def drop(self, name):
        for p in self.partitions():
            if p["name"] == name:
                self.entries[p["entry"]:p["entry"] + ENTRY_SIZE] = b"\0" * ENTRY_SIZE
                return p
        raise KeyError(name)

    def extend(self, name, first, last):
        for p in self.partitions():
            if p["name"] == name:
                struct.pack_into("<QQ", self.entries, p["entry"] + 32, first, last)
                return p
        raise KeyError(name)

    def set_usable(self, first, last):
        self.first_usable, self.last_usable = first, last

    def serialize(self, primary=True, total=0):
        entries = bytes(self.entries)
        ecrc = gpt_crc(entries)
        hdr = bytearray(self.hdr)
        hdr[16:20] = b"\0\0\0\0"
        if primary:
            my_lba, other_lba, entries_lba = self.current_lba, self.backup_lba, self.entries_lba
        else:
            my_lba, other_lba, entries_lba = total - 1, 1, total - 33
        struct.pack_into("<Q", hdr, 24, my_lba)
        struct.pack_into("<Q", hdr, 32, other_lba)
        struct.pack_into("<Q", hdr, 40, self.first_usable)
        struct.pack_into("<Q", hdr, 48, self.last_usable)
        struct.pack_into("<16s", hdr, 56, self.disk_guid)
        struct.pack_into("<Q", hdr, 72, entries_lba)
        struct.pack_into("<I", hdr, 80, ENTRIES)
        struct.pack_into("<I", hdr, 84, ENTRY_SIZE)
        struct.pack_into("<I", hdr, 88, ecrc)
        struct.pack_into("<I", hdr, 16, gpt_crc(bytes(hdr)))
        hdr512 = bytes(hdr) + b"\0" * (SECTOR - len(hdr))
        return (hdr512 + entries) if primary else (entries + hdr512)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--disk", required=True, help="dump containing the primary GPT (LBA0..)")
    ap.add_argument("--out", required=True, help="directory for the generated blobs")
    ap.add_argument("--drop", nargs="*", default=DROP_DEFAULT)
    ap.add_argument(
        "--layout",
        choices=["huawei", "std"],
        default="huawei",
        help="huawei: keep last_usable=total-1 and skip the backup blob; "
        "std: last_usable=total-34 and emit a backup GPT",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    g = GPT(args.disk)
    total = g.backup_lba + 1
    before = g.partitions()
    old_entries = bytes(g.entries)

    userdata = next((p for p in before if p["name"] == "userdata"), None)
    if userdata is None:
        sys.exit("no userdata partition in this GPT")

    dropped = []
    for name in args.drop:
        try:
            dropped.append(g.drop(name))
        except KeyError:
            print(f"warn: {name} not present, skipping")

    if not dropped:
        sys.exit("nothing dropped, nothing to do")

    # only grow backwards, and only into space that is actually contiguous
    lo = min(p["first"] for p in dropped)
    new_first = lo
    hi = max(p["last"] for p in dropped)
    if hi + 1 != userdata["first"] or lo >= userdata["first"]:
        sys.exit("dropped partitions are not contiguous with userdata; refusing")

    if args.layout == "huawei":
        new_last = total - 1
        last_usable = total - 1
    else:
        new_last = total - 34
        last_usable = total - 34

    g.extend("userdata", new_first, new_last)
    g.set_usable(34, last_usable)
    primary = g.serialize(primary=True)
    backup = g.serialize(primary=False, total=total) if args.layout == "std" else b""
    new_entries = bytes(g.entries)

    # re-parse what we just built, independently of the writer
    chk = bytearray(primary)
    hdr = chk[:92]
    body = bytearray(hdr)
    body[16:20] = b"\0\0\0\0"
    assert gpt_crc(bytes(body)) == struct.unpack_from("<I", hdr, 16)[0]
    assert gpt_crc(bytes(chk[SECTOR:])) == struct.unpack_from("<I", hdr, 88)[0]
    assert struct.unpack_from("<I", hdr, 80)[0] == ENTRIES

    after = GPT.__new__(GPT)
    after.hdr = bytearray(primary[:92])
    after.entries = bytearray(primary[SECTOR:])
    after.n_entries = ENTRIES
    after.entry_size = ENTRY_SIZE

    sectors = new_last - new_first + 1
    kib = sectors * SECTOR // 1024
    print(f"drop: {', '.join(p['name'] for p in dropped)}")
    print(f"userdata: first={new_first} last={new_last} sectors={sectors} "
          f"bytes={sectors * SECTOR} kib={kib} "
          f"({sectors * SECTOR / 2**30:.3f} GiB)")
    print(f"layout={args.layout} first_usable=34 last_usable={last_usable} total={total}")
    print("resulting table:")
    for p in after.partitions():
        print(f"  p{p['index']:<3} {p['name']:20s} {p['first']:<10} {p['last']:<10} "
              f"{(p['last'] - p['first'] + 1) * SECTOR / 2**30:8.3f} GiB")

    if args.dry_run:
        return
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "gpt-primary.bin"), "wb") as f:
        f.write(primary)
    if backup:
        with open(os.path.join(args.out, "gpt-backup.bin"), "wb") as f:
            f.write(backup)

    geometry = [
        f"GPT_LAYOUT={args.layout}",
        f"TOTAL_SECTORS={total}",
        f"USERDATA_FIRST={new_first}",
        f"USERDATA_LAST={new_last}",
        f"USERDATA_SECTORS={sectors}",
        f"USERDATA_KIB={kib}",
        f"USERDATA_BYTES={sectors * SECTOR}",
        f"OLD_ENTRIES_SHA256={hashlib.sha256(old_entries).hexdigest()}",
        f"NEW_ENTRIES_SHA256={hashlib.sha256(new_entries).hexdigest()}",
    ]
    with open(os.path.join(args.out, "geometry.env"), "w") as f:
        f.write("\n".join(geometry) + "\n")
    print(f"wrote {args.out}/gpt-primary.bin ({len(primary)} bytes)"
          + (f" and gpt-backup.bin ({len(backup)} bytes)" if backup else "")
          + f", {args.out}/geometry.env")


if __name__ == "__main__":
    main()

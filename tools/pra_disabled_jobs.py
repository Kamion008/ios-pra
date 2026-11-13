#!/usr/bin/env python3
"""Turn launchd jobs off through its disabled database on the PRA root.

launchd reads /private/var/db/com.apple.xpc.launchd/disabled.plist and will
not spawn a job whose label maps to true.  On this phone five jobs run
without the hardware they need, exit(78) within a second, and get respawned
every 10 s: locationd, bluetoothd, fairplayd.H2, nanotimekitcompaniond and
WirelessRadioManager.  Measured from launchd's own log that is ~34 launches
a minute - most of the I/O after Setup starts, plus a crash report per
failure.

The file is one 4 KiB allocation block with a 459-byte fork, so a rewritten
plist has to fit the old fork length exactly; otherwise the catalog record
and the block bitmap would have to change.  The payload is therefore a
binary plist padded with a throwaway boolean key to exactly FORK bytes.

  pra_disabled_jobs.py --list
  pra_disabled_jobs.py --add com.apple.locationd[,com.apple.bluetoothd...]
  pra_disabled_jobs.py --restore      # put the saved original block back

Every write is read back and compared.  The original block is kept in
/tmp/opencode/disabled_block.orig (bs=512 LBA from --lba).
"""
import argparse
import os
import plistlib
import subprocess
import sys

SECTOR = 512
DEFAULT_SERIAL = "57U7N17912003349"
BLOCK = 4096
DEFAULT_LBA = 30003504          # p58 block 2411046, verified against the catalog
DEFAULT_FORK = 459
SAVE = "/tmp/opencode"


def adb(serial, *args, binary=False):
    p = subprocess.run(["adb", "-s", serial] + list(args),
                       capture_output=True, text=not binary)
    if p.returncode != 0:
        raise SystemExit("adb failed: %s" %
                         (p.stderr if not binary else p.stderr.decode(
                             "utf-8", "replace")))
    return p.stdout


def read_block(serial, lba):
    out = adb(serial, "exec-out",
              "dd if=/dev/block/mmcblk0 bs=%d skip=%d count=%d 2>/dev/null"
              % (SECTOR, lba, BLOCK // SECTOR), binary=True)
    if len(out) != BLOCK:
        raise SystemExit("short read: %d bytes" % len(out))
    return out


def write_block(serial, lba, data):
    up = os.path.join(SAVE, "disabled_up.bin")
    open(up, "wb").write(data)
    adb(serial, "push", up, "/tmp/db.bin")
    adb(serial, "shell", "dd if=/tmp/db.bin of=/dev/block/mmcblk0 bs=%d "
                         "seek=%d count=%d 2>/dev/null"
                         % (SECTOR, lba, BLOCK // SECTOR))
    back = read_block(serial, lba)
    if back != data:
        raise SystemExit("read-back mismatch")
    return back


def fit(entries, fork):
    """Encode entries as a binary plist of exactly `fork` bytes."""
    raw = plistlib.dumps(entries, fmt=plistlib.FMT_BINARY, sort_keys=True)
    if len(raw) == fork:
        return raw
    if len(raw) > fork:
        raise SystemExit("plist needs %d bytes, the fork holds %d; a rewrite "
                         "would need a catalog change" % (len(raw), fork))
    for n in range(0, fork):
        probe = dict(entries)
        probe["pra.pad." + "x" * n] = True
        raw = plistlib.dumps(probe, fmt=plistlib.FMT_BINARY, sort_keys=True)
        if len(raw) == fork:
            return raw
    raise SystemExit("cannot pad to exactly %d bytes" % fork)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default=os.environ.get("PRA_SERIAL",
                                                       DEFAULT_SERIAL))
    ap.add_argument("--lba", type=int, default=DEFAULT_LBA)
    ap.add_argument("--fork", type=int, default=DEFAULT_FORK)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--add", metavar="LABEL[,LABEL...]")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.list or args.add or args.restore):
        ap.error("one of --list/--add/--restore is required")

    os.makedirs(SAVE, exist_ok=True)
    blk = read_block(args.serial, args.lba)
    entries = plistlib.loads(blk[:args.fork])
    print("live disabled.plist: %d entries, %d-byte fork"
          % (len(entries), args.fork))
    for k in sorted(entries):
        if entries[k]:
            print("  disabled  %s" % k)

    if args.list:
        return

    if args.restore:
        p = os.path.join(SAVE, "disabled_block.orig")
        if not os.path.exists(p):
            raise SystemExit("%s missing; cannot restore" % p)
        write_block(args.serial, args.lba, open(p, "rb").read())
        print("restored the original block")
        return

    if not os.path.exists(os.path.join(SAVE, "disabled_block.orig")):
        open(os.path.join(SAVE, "disabled_block.orig"), "wb").write(blk)
        print("saved original block: %s/disabled_block.orig" % SAVE)

    added = []
    for label in args.add.split(","):
        label = label.strip()
        if not label:
            continue
        if entries.get(label) is True:
            print("already disabled: %s" % label)
            continue
        entries[label] = True
        added.append(label)
    if not added:
        return
    payload = fit(entries, args.fork)
    full = payload + b"\x00" * (BLOCK - len(payload))
    print("adding: %s (%d bytes, padded to the fork)"
          % (", ".join(added), len(payload)))
    if args.dry_run:
        print("dry run: nothing written")
        return
    write_block(args.serial, args.lba, full)
    check = plistlib.loads(read_block(args.serial, args.lba)[:args.fork])
    ok = [l for l in added if check.get(l) is True]
    print("written and read back; disabled now: %d entries, added %d/%d"
          % (len(check), len(ok), len(added)))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Parse a PRADMP01 blob written by shim/pra/probe.c.

Usage: pra_parse_dump.py dump.bin

The dump lives at erecovery_kernel + 16 MiB (LBA 786432) and is 25 sectors.
"""
import struct
import sys

MAGIC = b"PRADMP01"
HDR = "<8sII8Q"                     # magic, version, ncand, 8 sysregs
CAND = "<III"


def ram_name(v):
    if 0x31000000 <= v < 0x32A40000:
        return "graphic carveout"
    if 0x5D000000 <= v < 0x60000000:
        return "logo buffer"
    if 0x80000000 <= v <= 0xDFFFFFFF:
        return "upper RAM bank"
    if 0x00400000 <= v < 0x60000000:
        return "lower RAM"
    return ""


def main(path):
    d = open(path, "rb").read()
    if len(d) < 0x3000:
        print(f"short dump: {len(d)} bytes")
    magic, version, ncand, *regs = struct.unpack_from(HDR, d, 0)
    if magic != MAGIC:
        print(f"bad magic {magic!r} (want {MAGIC!r})")
        return 1
    names = ["CurrentEL", "MIDR_EL1", "MPIDR_EL1", "CNTFRQ_EL0",
             "SCTLR_EL1", "ID_AA64MMFR0", "ID_AA64PFR0", "CTR_EL0"]
    print(f"version {version}, {ncand} candidates")
    for n, v in zip(names, regs):
        print(f"  {n:14s} = 0x{v:016x}")

    off = struct.calcsize(HDR)
    print("\ncandidates (page-aligned RAM-looking values):")
    for i in range(ncand):
        win, woff, val = struct.unpack_from(CAND, d, off + i * 12)
        wname = ("DSS", "MMBUF", "PCTRL")[win] if win < 3 else f"win{win}"
        print(f"  {wname}[0x{woff:03x}] = 0x{val:08x}  {ram_name(val)}")

    off += 32 * 12
    for wname in ("DSS", "MMBUF", "PCTRL"):
        words = struct.unpack_from("<1024I", d, off)
        off += 4096
        print(f"\n{wname} window (non-zero):")
        for i, v in enumerate(words):
            if v:
                print(f"  [{i * 4:03x}] = 0x{v:08x}  {ram_name(v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dump.bin"))

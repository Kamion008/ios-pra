#!/usr/bin/env python3
"""kernsym.py - offline symbolication of kernel VAs against the CI kernel
Mach-O (kernel.development.pra). Parses LC_SEGMENT_64 + LC_SYMTAB, then maps
VA -> nearest symbol below (function or data). Usage:
    python3 -I work/kernsym.py 0xfffffff007xxxxxx [more vas...]
    python3 -I work/kernsym.py --dump      (print segments + base + sym count)
All arithmetic printed; never do slide math in your head.
"""
import struct, sys, bisect

import os
KERN = "/tmp/art0173/kernel.development.pra"
args = sys.argv[1:]
if args and args[0] != "--dump" and os.path.exists(args[0]):
    KERN = args[0]
    args = args[1:]

data = open(KERN, "rb").read()
magic, cputype, cpusub, filetype, ncmds, sizeofcmds, flags = \
    struct.unpack_from("<IIIIIII", data, 0)
assert magic == 0xFEEDFACF, f"not MH_MAGIC_64: {magic:#x}"

segs, symtab = [], None
o = 32
for _ in range(ncmds):
    cmd, cmdsize = struct.unpack_from("<II", data, o)
    if cmd == 0x19:  # LC_SEGMENT_64
        name = data[o+8:o+24].split(b"\0")[0].decode()
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, o+24)
        segs.append((name, vmaddr, vmsize, fileoff, filesize))
    elif cmd == 0x2:  # LC_SYMTAB
        symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, o+8)
        symtab = (symoff, nsyms, stroff, strsize)
    o += cmdsize

text = next((s for s in segs if s[0] == "__TEXT"), None)
print(f"kernel: {len(data)} bytes, {len(segs)} segments, symtab={symtab is not None}")
for name, va, vsz, fo, fsz in segs:
    print(f"  {name:16s} vm {va:#x}..{va+vsz:#x} file {fo:#x}..{fo+fsz:#x}")

syms = []
if symtab:
    symoff, nsyms, stroff, strsize = symtab
    strings = data[stroff:stroff+strsize]
    for i in range(nsyms):
        n_strx, n_type, n_sect, n_desc, n_value = \
            struct.unpack_from("<IBBHQ", data, symoff + 16*i)
        end = strings.find(b"\0", n_strx)
        nm = strings[n_strx:end].decode("ascii", "replace")
        if nm and n_value:
            syms.append((n_value, nm))
    syms.sort()
    print(f"symbols: {len(syms)} (first {syms[0][0]:#x} {syms[0][1]}, "
          f"last {syms[-1][0]:#x} {syms[-1][1]})")

sym_addrs = [s[0] for s in syms]

def va_to_off(va):
    for name, sva, vsz, fo, fsz in segs:
        if sva <= va < sva + vsz:
            return fo + (va - sva), name
    return None, None

def sym_for(va):
    i = bisect.bisect_right(sym_addrs, va) - 1
    if i < 0:
        return None, None
    a, nm = syms[i]
    return nm, va - a

def show(va):
    off, seg = va_to_off(va)
    nm, d = sym_for(va)
    where = f"seg={seg} fileoff={off:#x}" if off is not None else "UNMAPPED"
    delta = f" +{d:#x}" if nm and d else ""
    print(f"  {va:#x} -> {nm or '?'}{delta}  [{where}]")

if args and args[0] == "--dump":
    pass
else:
    for a in args:
        try:
            show(int(a, 16))
        except ValueError:
            print(f"  {a}: not hex")

#!/usr/bin/env python3
"""Pack a flat binary + ADT into the SWEETXNU v1 payload.

This is the same on-wire format as mkpayload.py (which parses a Mach-O), for
payloads that are already flat and linked at a known physical address. The
PRA handoff test payload and any future non-Mach-O stub use it.

  mkpayload_flat.py BIN LOAD_ADDR ENTRY VMSIZE ADT OUT [--cmdline "..."]

PHYS_BASE/MEM_SIZE come from the ADT's /chosen dram-base/dram-size, exactly
as mkpayload.py does, so the loader and the kernel agree on the window.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

BOOT_LINE_LENGTH = 608
CMDLINE = 0x48
SEG_TABLE = CMDLINE + BOOT_LINE_LENGTH		# 0x2a8


def adt_dram(blob):
	root, _ = adt.parse(blob)
	chosen = next(c for c in root.children if c.name == 'chosen')
	return (struct.unpack('<Q', chosen.prop('dram-base'))[0],
	        struct.unpack('<Q', chosen.prop('dram-size'))[0])


def build(bin_path, load, entry, vmsize, adt_path, cmdline):
	image = open(bin_path, 'rb').read()
	adt_blob = open(adt_path, 'rb').read()
	phys_base, mem_size = adt_dram(adt_blob)
	virt_base = load
	kernel_end = (load + vmsize + 0xfff) & ~0xfff

	pieces = [(load, vmsize, image)]
	hdr_size = SEG_TABLE + 32 * len(pieces)
	out = bytearray(hdr_size)
	seg_table = []
	for vmaddr, vsz, data in pieces:
		off = len(out)
		out += data
		out += b'\0' * (-len(out) & 0xf)
		seg_table.append((vmaddr, vsz, off, len(data)))
	adt_off = len(out)
	out += adt_blob
	out += b'\0' * (-len(out) & 0xf)

	struct.pack_into('<8sII', out, 0, b'SWEETXNU', 1, len(pieces))
	struct.pack_into('<7Q', out, 0x10, virt_base, entry, adt_off,
	                 len(adt_blob), kernel_end, phys_base, mem_size)
	cl = cmdline.encode()[:BOOT_LINE_LENGTH - 1]
	out[CMDLINE:CMDLINE + len(cl)] = cl
	for i, t in enumerate(seg_table):
		struct.pack_into('<4Q', out, SEG_TABLE + 32 * i, *t)

	info = dict(virt_base=hex(virt_base), entry=hex(entry),
	            kernel_end=hex(kernel_end), phys_base=hex(phys_base),
	            mem_size=hex(mem_size), adt_off=hex(adt_off),
	            adt_size=len(adt_blob), size=len(out))
	return bytes(out), info


if __name__ == '__main__':
	ap = argparse.ArgumentParser()
	ap.add_argument('binary')
	ap.add_argument('load_addr')
	ap.add_argument('entry')
	ap.add_argument('vmsize')
	ap.add_argument('adt')
	ap.add_argument('out')
	ap.add_argument('--cmdline', default='debug=0x8 serial=0 cpus=1')
	a = ap.parse_args()
	blob, info = build(a.binary, int(a.load_addr, 0), int(a.entry, 0),
	                   int(a.vmsize, 0), a.adt, a.cmdline)
	open(a.out, 'wb').write(blob)
	for k, v in info.items():
		print(f'{k}: {v}')

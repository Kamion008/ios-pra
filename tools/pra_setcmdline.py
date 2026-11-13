#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Show or replace the boot command line inside a raw p27 image.

The cmdline lives in the payload header that tools/mkpayload.py writes, so it
can be changed without rebuilding the kernel or re-running pra_package.sh:

    tools/pra_setcmdline.py IMAGE                 # print it
    tools/pra_setcmdline.py IMAGE "args ..."      # replace it (in place)

Layout: payload at file offset 2048 + 0x80000, magic "SWEETXNU" at +0,
version at +8, cmdline at +0x48, 608 bytes.
"""
import struct
import sys

PAYLOAD = 2048 + 0x80000
MAGIC = b'SWEETXNU'
CMDLINE_OFF = 0x48
BOOT_LINE_LENGTH = 608


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    path, new = sys.argv[1], (sys.argv[2] if len(sys.argv) == 3 else None)

    with open(path, 'r+b') as f:
        f.seek(PAYLOAD)
        head = f.read(0x2a8)
        if head[:8] != MAGIC:
            sys.exit(f'{path}: no SWEETXNU payload at {PAYLOAD}')
        version, = struct.unpack_from('<I', head, 8)
        if version != 1:
            sys.exit(f'{path}: payload version {version}, expected 1')
        old = head[CMDLINE_OFF:CMDLINE_OFF + BOOT_LINE_LENGTH].split(b'\0')[0]
        if new is None:
            print(old.decode())
            return
        blob = new.encode()
        if len(blob) >= BOOT_LINE_LENGTH:
            sys.exit(f'cmdline is {len(blob)} bytes, limit {BOOT_LINE_LENGTH - 1}')
        f.seek(PAYLOAD + CMDLINE_OFF)
        f.write(blob + b'\0' * (BOOT_LINE_LENGTH - len(blob)))
    print(f'{path}: cmdline set ({len(blob)} bytes)')


if __name__ == '__main__':
    main()

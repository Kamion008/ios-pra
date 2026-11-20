#!/usr/bin/env python3
"""Minimal flattened-device-tree reader + phandle resolver.

Usage:
  fdt_dump.py FDT [NODE-SUBSTRING]         print nodes/properties
  fdt_dump.py FDT --phandles               print phandle -> path map
  fdt_dump.py FDT --node PATH              print one node by exact path
"""
import struct
import sys


def parse(data):
    magic, totalsize, off_struct, off_strings, off_rsv, version, \
        last_comp, boot_cpu, size_strings, size_struct = \
        struct.unpack('>10I', data[:40])
    if magic != 0xd00dfeed:
        raise SystemExit('bad fdt magic %08x' % magic)
    strings = data[off_strings:off_strings + size_strings]

    def name_at(off):
        end = strings.find(b'\0', off)
        return strings[off:end].decode('latin1')

    nodes = []
    stack = []          # [(path, props)]
    pos = off_struct
    while True:
        tok = struct.unpack('>I', data[pos:pos + 4])[0]
        pos += 4
        if tok == 1:    # BEGIN_NODE
            end = data.find(b'\0', pos)
            name = data[pos:end].decode('latin1')
            pos = (end + 4) & ~3
            if stack:
                path = stack[-1][0].rstrip('/') + '/' + name
            else:
                path = '/'
            stack.append((path, []))
        elif tok == 2:  # END_NODE
            nodes.append(stack.pop())
        elif tok == 3:  # PROP
            length, nameoff = struct.unpack('>II', data[pos:pos + 8])
            pos += 8
            raw = data[pos:pos + length]
            pos = (pos + length + 3) & ~3
            stack[-1][1].append((name_at(nameoff), raw))
        elif tok == 4:  # NOP
            pass
        elif tok == 9:  # END
            break
        else:
            raise SystemExit('bad token %d at %d' % (tok, pos - 4))
    return nodes


def fmt(raw):
    if not raw:
        return '<empty>'
    try:
        s = raw.decode('utf-8')
        if s.isprintable() and '\0' not in s:
            return repr(s)
    except UnicodeDecodeError:
        pass
    if len(raw) % 4 == 0:
        vals = struct.unpack('>%dI' % (len(raw) // 4), raw)
        return ' '.join('%08x' % v for v in vals)
    return raw.hex()


def main():
    data = open(sys.argv[1], 'rb').read()
    nodes = parse(data)
    by_path = {p: props for p, props in nodes}

    if len(sys.argv) > 2 and sys.argv[2] == '--phandles':
        m = {}
        for p, props in nodes:
            for name, raw in props:
                if name in ('phandle', 'linux,phandle') and len(raw) == 4:
                    m[struct.unpack('>I', raw)[0]] = p
        for ph in sorted(m):
            print('%08x %s' % (ph, m[ph]))
        return

    if len(sys.argv) > 2 and sys.argv[2] == '--node':
        p = sys.argv[3]
        if p not in by_path:
            raise SystemExit('no such node: %s' % p)
        print(p)
        for name, raw in by_path[p]:
            print('    %-28s %s' % (name, fmt(raw)))
        return

    needle = sys.argv[2] if len(sys.argv) > 2 else None
    for path, props in nodes:
        if needle and needle not in path:
            continue
        print(path)
        for name, raw in props:
            print('    %-28s %s' % (name, fmt(raw)))


if __name__ == '__main__':
    main()

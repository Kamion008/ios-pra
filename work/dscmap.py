#!/usr/bin/env python3
"""dscmap.py - read bytes from the iOS 16.7.16 dyld shared cache extraction
(~/dsc-x/cache) and decode syscall stubs.

Empirical layout (2026-11-16, all cross-checked at runtime):
- main file header: magic 'dyld_v1   arm64'; mappingOffset/Count u32 @+0x10/+0x14;
  32-byte mapping entries {u64 addr, u64 size, u64 fileoff, u32 maxProt, u32 initProt}.
  image table A @0x1fd0 (scan-derived): classic dyld_cache_image_info
  {u64 addr, u64 modTime, u64 inode, u32 pathOff, u32 pad}, 2475 entries,
  upper region 0x1a4610000..0x20cd92000, pathOff into main file (verified sane).
  image table B @+0x88/+0x90 (0x15530, 2710): {u64, u64, u64 addr@+0x10,
  u32 pathOff@+0x18, u32 pad}, covers lower region 0x1800b8000.. AND repeats the
  upper region; its path pool does NOT resolve reliably -> used only as an
  address hint, names come from Mach-O parsing.
- subcaches: own dyld_v1 header, mappings at +0x10/+0x14, 32-byte entries.
  file offset = mapping.fileoff + (vm - mapping.addr).
  Runtime anchor (handoff cross-check): vm 0x1c2611030 -> subcache .19 @ 0x5f69030.

Stub model (established from raw words at the anchor): stubs are tightly
packed 12-byte [MOVN x16,#imm; SVC #0x80; RET] runs with consecutive traps.
A thread blocked in trap N has saved pc = SVC_addr+4 = its own stub's RET,
so in-flight trap = imm of MOVN at pc-8 (MOVN -> x16 = ~imm).
"""
import struct, os, sys, glob, bisect

CACHE_DIR = os.path.expanduser("~/dsc-x/cache")
MAIN = os.path.join(CACHE_DIR, "dyld_shared_cache_arm64")
SUBCACHE_GLOB = os.path.join(CACHE_DIR, "dyld_shared_cache_arm64.*")

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_ID_DYLIB = 0x0D

class DSC:
    def __init__(self, cache_dir=CACHE_DIR, verbose=False):
        self.dir = cache_dir
        self.verbose = verbose
        self.main = open(MAIN, "rb").read()
        assert self.main[:7] == b"dyld_v1", "bad main magic"
        self.mappings = []
        mo, mc = self._u32(self.main, 0x10), self._u32(self.main, 0x14)
        for i in range(mc):
            o = mo + 32*i
            self.mappings.append((self._u64(self.main, o), self._u64(self.main, o+8),
                                  self._u64(self.main, o+16), "MAIN"))
        for f in sorted(glob.glob(SUBCACHE_GLOB)):
            if f.endswith(".symbols"):
                continue
            b = open(f, "rb").read(0x400)
            if b[:7] != b"dyld_v1":
                print(f"WARN: {f}: no dyld_v1 magic, skipped", file=sys.stderr)
                continue
            mo, mc = self._u32(b, 0x10), self._u32(b, 0x14)
            fsize = os.path.getsize(f)
            for i in range(mc):
                o = mo + 32*i
                a, s, fo = self._u64(b, o), self._u64(b, o+8), self._u64(b, o+16)
                if a == 0 and s == 0:
                    continue
                if a < 0x100000000 or a + s > 0x300000000 or fo + s > fsize + 0x1000:
                    print(f"WARN: {os.path.basename(f)} map{i} addr={a:#x} size={s:#x} "
                          f"fileoff={fo:#x} implausible, skipped", file=sys.stderr)
                    continue
                self.mappings.append((a, s, fo, os.path.basename(f)))
        self.mappings.sort()
        self.map_addrs = [m[0] for m in self.mappings]
        # image address hints from both tables
        self.images = set()
        b_off, b_cnt = self._u32(self.main, 0x88), self._u32(self.main, 0x90)
        for i in range(b_cnt):
            self.images.add(self._u64(self.main, b_off + 32*i + 0x10))
        e = 0x1fd0
        while True:
            a = self._u64(self.main, e)
            po = self._u32(self.main, e+24)
            if not (0x180000000 <= a < 0x260000000 and 0x200 <= po < len(self.main)
                    and self.main[po] != 0):
                break
            self.images.add(a)
            e += 32
        self.images = sorted(self.images)
        self._linkedit = None
        self._macho_cache = {}

    @staticmethod
    def _u32(b, o): return struct.unpack_from("<I", b, o)[0]
    @staticmethod
    def _u64(b, o): return struct.unpack_from("<Q", b, o)[0]

    def mapping_of(self, vm):
        i = bisect.bisect_right(self.map_addrs, vm) - 1
        if i < 0:
            return None
        a, s, f, fname = self.mappings[i]
        if vm >= a + s:
            return None
        return (fname, f, vm - a)

    def read(self, vm, n):
        m = self.mapping_of(vm)
        if m is None:
            return None
        fname, f, off = m
        with open(os.path.join(self.dir, fname), "rb") as fh:
            fh.seek(off)
            d = fh.read(n)
        return d if len(d) == n else None

    def macho(self, img_addr):
        """Parse Mach-O header at img_addr -> (install_name, [(vmaddr, vmsize)...]).
        Cached. Returns None if not a Mach-O."""
        if img_addr in self._macho_cache:
            return self._macho_cache[img_addr]
        hdr = self.read(img_addr, 0x1000)
        if hdr is None or struct.unpack_from("<I", hdr, 0)[0] != MH_MAGIC_64:
            self._macho_cache[img_addr] = None
            return None
        ncmds, sizeofcmds = struct.unpack_from("<II", hdr, 16)
        segs, install = [], None
        o = 32
        end = min(32 + sizeofcmds, len(hdr))
        while o + 8 <= end and ncmds > 0:
            cmd, cmdsize = struct.unpack_from("<II", hdr, o)
            if cmdsize < 8 or o + cmdsize > end:
                break
            if cmd == LC_SEGMENT_64:
                vmaddr, vmsize = struct.unpack_from("<QQ", hdr, o+24)
                segs.append((vmaddr, vmsize))
            elif cmd == LC_ID_DYLIB and install is None:
                name_off = struct.unpack_from("<I", hdr, o+8)[0]  # lc_str: from cmd start
                p = img_addr + o + name_off
                nm = self.read(p, 300)
                if nm:
                    nm = nm.split(b"\0")[0].decode("ascii", "replace")
                    install = nm
            ncmds -= 1
            o += cmdsize
        out = (install, segs) if install or segs else None
        self._macho_cache[img_addr] = out
        return out

    def contain(self, vm):
        """Best image for vm: largest image addr <= vm whose Mach-O covers vm."""
        idx = bisect.bisect_right(self.images, vm) - 1
        for j in range(idx, max(-1, idx - 6), -1):
            ia = self.images[j]
            mh = self.macho(ia)
            if mh is None:
                continue
            install, segs = mh
            for va, vs in segs:
                if va <= vm < va + vs:
                    return (ia, install, va, va + vs)
            # image found but vm past its segments: gap after this image
            if segs:
                hi = max(va+vs for va, vs in segs)
                if vm >= hi:
                    return (ia, install + " [PAST SEGMENT END]", hi, hi)
        return None

    # ---- stub decode ----
    # MOVN Xd,#imm: sf=1 opc=00 100101 hw imm16 Rd  ->  x16 variant base:
    MOVN_X16 = (1 << 31) | (0b00 << 29) | (0b100101 << 23)
    assert MOVN_X16 == 0x92800000
    SVC_0x80 = (0b11010100 << 24) | 1 | (0x80 << 5)
    assert SVC_0x80 == 0xD4001001
    RET_W = 0xD65F0000 | (30 << 5)
    assert RET_W == 0xD65F03C0

    def decode_at(self, unslid_pc):
        """Saved-pc shapes for a thread blocked in a syscall (xnu stores pc = SVC+4):
        mach trap: [MOVN x16,#N @pc-8][SVC @pc-4][RET @pc]   -> trap = ~(N) = -(N+1)
        BSD syscall: [MOVZ x16,#N @pc-8][SVC @pc-4][B.cond @pc] -> sysnum = N
        (raw ELR shape kept for safety: [MOVN/MOVZ @pc-4][SVC @pc])."""
        raw = self.read(unslid_pc - 8, 16)
        if raw is None or len(raw) < 16:
            return {"kind": "unmapped"}
        w = struct.unpack("<IIII", raw)   # w[0]@pc-8, w[1]@pc-4, w[2]@pc, w[3]@pc+4
        d = {"words": [f"{x:#010x}" for x in w]}
        MOVZ_X16 = 0xD2800010             # sf=1 opc=10 100101 hw=0 imm16 Rd=16
        for opc_base, name in ((self.MOVN_X16, "MOVN"), (MOVZ_X16, "MOVZ")):
            if (w[0] & 0xFFE0001F) == (opc_base | 16) and w[1] == self.SVC_0x80:
                imm = (w[0] >> 5) & 0xFFFF
                hw = (w[0] >> 21) & 3
                x16 = ~(imm << (32*hw)) & (2**64 - 1)
                val = (x16 - 2**64) if x16 >> 63 else x16
                kind = "stub-mach (pc=RET: saved pc = SVC+4)" if name == "MOVN" \
                    else "stub-bsd (pc=B.cond: saved pc = SVC+4)"
                if name == "MOVZ":
                    val = imm             # MOVZ does not invert
                d.update(kind=kind, movn_vm=unslid_pc - 8, movn_imm=imm, movn_hw=hw,
                         x16_signed=val, trap=val)
                return d
        if w[2] == self.SVC_0x80 and (w[1] & 0xFFE0001F) in \
                ((self.MOVN_X16 | 16), (MOVZ_X16 | 16)):
            imm = (w[1] >> 5) & 0xFFFF
            hw = (w[1] >> 21) & 3
            x16 = ~(imm << (32*hw)) & (2**64 - 1) if (w[1] & 0xFC000000) == \
                (self.MOVN_X16 & 0xFC000000) else imm
            val = (x16 - 2**64) if x16 >> 63 else x16
            d.update(kind="stub (pc=SVC: raw ELR)", movn_vm=unslid_pc - 4,
                     movn_imm=imm, movn_hw=hw, x16_signed=val, trap=val)
            return d
        d["kind"] = "not-stub"
        return d

def trap_names(src="/home/kamion008/Ai/ios/ios-pra/xnu-src/osfmk/kern/syscall_sw.c"):
    import re
    names = {}
    for m in re.finditer(r"/\* (\d+) \*/ MACH_TRAP\(([A-Za-z_0-9]+),", open(src).read()):
        n = -int(m.group(1))
        if n not in names:          # first wins (47 = mach_msg2_trap on arm64)
            names[n] = m.group(2)
    return names

def bsd_names(src="/home/kamion008/Ai/ios/ios-pra/xnu-src/bsd/kern/syscalls.master"):
    """Parse positive BSD syscall numbers from syscalls.master lines."""
    import re
    names = {}
    for line in open(src, errors="replace"):
        m = re.match(r"\s*(\d+)\s+AUE_\w+\s+\w+\s+\{\s*(?:int|user_ssize_t|uint\d+|void|kern_return_t)\s+([A-Za-z_0-9]+)\(", line)
        if m:
            names[int(m.group(1))] = m.group(2)
    return names

def main():
    dsc = DSC(verbose=True)
    print(f"mappings: {len(dsc.mappings)}; image address hints: {len(dsc.images)}")
    # anchor checks
    vm = 0x1c2611030
    m = dsc.mapping_of(vm)
    assert m and m[0] == "dyld_shared_cache_arm64.19" and m[2] == 0x5f69030, m
    print(f"anchor vm {vm:#x} -> {m[0]} @ {m[2]:#x}  (handoff match OK)")
    c = dsc.contain(vm)
    print(f"anchor containment: {c}")
    d = dsc.decode_at(vm)
    print(f"anchor stub decode: {d}")
    tn = trap_names()
    print(f"  trap {d['trap']} = {tn.get(d['trap'])}")
    # xnu arm64: trap -47 = mach_msg2_trap (osfmk/kern/syscall_sw.c:154, __LP64__ branch)
    assert d["kind"].startswith("stub") and d["trap"] == -47, d

if __name__ == "__main__":
    main()

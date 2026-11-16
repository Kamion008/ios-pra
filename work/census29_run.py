#!/usr/bin/env python3
"""census29_run.py - full census: decode every distinct sampled PC in ring29,
classify stub(trap N) vs not-a-stub, name the containing image, count per
process/thread. Prints all intermediates. Requires work/census29.py JSON step.
"""
import sys, os, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dscmap import DSC, trap_names, bsd_names
import importlib.util
spec = importlib.util.spec_from_file_location(
    "census29", os.path.join(os.path.dirname(os.path.abspath(__file__)), "census29.py"))

RING = sys.argv[1] if len(sys.argv) > 1 else "work/ring29.txt"
sys.argv = [RING]  # census29 main guard not run; we re-parse inline instead

import re
re_sample = re.compile(r"^SMP --- sample (\d+)")
re_slide  = re.compile(r"^SMP (\S+)\[(\d+)\] slide 0x([0-9a-f]+) mh 0x([0-9a-f]+)")
re_thread = re.compile(r"^SMP (\S+) t(\d+) pc 0x([0-9a-f]+) lr 0x([0-9a-f]+) sp 0x([0-9a-f]+) bt(.*)")

samples, slides, cur = [], {}, None
for line in open(RING, errors="replace"):
    line = line.rstrip("\n")
    m = re_sample.match(line)
    if m:
        cur = {"n": int(m.group(1)), "threads": []}
        samples.append(cur)
        continue
    m = re_slide.match(line)
    if m:
        slides[m.group(1)] = int(m.group(3), 16)
        continue
    m = re_thread.match(line)
    if m and cur is not None:
        cur["threads"].append((m.group(1), int(m.group(2)), int(m.group(3), 16)))

dsc = DSC()
tn = trap_names()
bn = bsd_names()
pc_cnt = collections.Counter()
thr_pc = collections.defaultdict(collections.Counter)
for s in samples:
    for p, t, pc in s["threads"]:
        pc_cnt[(p, pc)] += 1
        thr_pc[(p, t)][pc] += 1

print(f"samples={len(samples)} threads={sum(pc_cnt.values())} distinct(proc,pc)={len(pc_cnt)}")
print(f"slides: " + ", ".join(f"{p}=0x{s:x}" for p, s in slides.items()))
print()

rows = []
for (p, pc), c in pc_cnt.most_common():
    slide = slides[p]
    u = pc - slide
    d = dsc.decode_at(u)
    cont = dsc.contain(u)
    trap = d.get("trap")
    name = tn.get(trap) if (trap is not None and trap < 0) else \
        bn.get(trap) if trap is not None else None
    row = {
        "proc": p, "pc": f"0x{pc:x}", "unslide": f"0x{u:x}", "count": c,
        "slide": f"0x{slide:x}",
        "kind": d.get("kind"),
        "movn_vm": f"0x{d['movn_vm']:x}" if "movn_vm" in d else None,
        "movn_imm": d.get("movn_imm"), "x16": d.get("x16_signed"),
        "trap": trap,
        "trap_name": name,
        "image": cont[1] if cont else None,
        "img_addr": f"0x{cont[0]:x}" if cont else None,
        "seg": f"[0x{cont[2]:x},0x{cont[3]:x})" if cont else None,
        "words": d.get("words"),
    }
    rows.append(row)
    print(f"{p:12s} pc {pc:#x} unslide {u:#x} n={c:<4d} {row['kind']}")
    if trap is not None:
        print(f"             trap/syscall {trap} = {name} "
              f"(raw imm {row['movn_imm']} @ {row['movn_vm']}, words {row['words']})")
    print(f"             image: {row['image']} @ {row['img_addr']} seg {row['seg']}")

json.dump({"slides": {p: f"0x{s:x}" for p, s in slides.items()},
           "rows": rows,
           "threads": {f"{p}/t{t}": {f"0x{pc:x}": n for pc, n in pcs.items()}
                       for (p, t), pcs in sorted(thr_pc.items())}},
          open("/tmp/census29_full.json", "w"), indent=1)
print("\nper-thread PC distribution (only threads with >1 distinct pc or non-dominant pc):")
for (p, t), pcs in sorted(thr_pc.items()):
    if len(pcs) > 1:
        print(f"  {p} t{t}: " + ", ".join(f"0x{pc:x}({n})" for pc, n in pcs.most_common()))

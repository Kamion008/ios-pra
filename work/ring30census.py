#!/usr/bin/env python3
"""ring30census.py - parse ring30 sampler lines (0173 format), split old vs
new boot by slide, census parked threads with kernel-side fields.
Prints everything; writes /tmp/ring30_census.json.
"""
import json, re, sys, collections

RING = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ring30.txt"
# this boot's slides (identified from the slide census)
NEW_SLIDES = {"b4b4000", "1a368000"}

re_sample = re.compile(r"^SMP --- sample (\d+)")
re_slide  = re.compile(r"^SMP (\S+)\[(\d+)\] slide 0x([0-9a-f]+) mh 0x([0-9a-f]+)")
re_thread = re.compile(
    r"^SMP (\S+) t(\d+) pc 0x([0-9a-f]+) lr 0x([0-9a-f]+) sp 0x([0-9a-f]+)")
re_th = re.compile(
    r"th=0x([0-9a-f]+) st=0x([0-9a-f]+) we=0x([0-9a-f]+) wq=0x([0-9a-f]+) "
    r"cont=0x([0-9a-f]+) kbt(.*)")

samples = []          # (n, is_new, threads)
slides_new = {}
cur = None
for line in open(RING, errors="replace"):
    line = line.rstrip("\n")
    m = re_sample.match(line)
    if m:
        cur = {"n": int(m.group(1)), "new": None, "threads": []}
        samples.append(cur)
        continue
    m = re_slide.match(line)
    if m and cur is not None:
        cur["new"] = m.group(3) in NEW_SLIDES
        if cur["new"]:
            slides_new[m.group(1)] = int(m.group(3), 16)
        continue
    m = re_thread.match(line)
    if m and cur is not None:
        th = {"proc": m.group(1), "t": int(m.group(2)),
              "pc": int(m.group(3), 16), "lr": int(m.group(4), 16),
              "sp": int(m.group(5), 16)}
        m2 = re_th.search(line)
        if m2:
            th["th"] = int(m2.group(1), 16)
            th["st"] = int(m2.group(2), 16)
            th["we"] = int(m2.group(3), 16)
            th["wq"] = int(m2.group(4), 16)
            th["cont"] = int(m2.group(5), 16)
            th["kbt"] = [int(x, 16) for x in m2.group(6).split()
                         if re.fullmatch(r"0x[0-9a-f]+", x)]
        bt = re.search(r"bt ([0-9a-fx ]+)", line)
        if bt:
            th["bt"] = [int(x, 16) for x in bt.group(1).split()
                        if re.fullmatch(r"0x[0-9a-f]+", x)]
        cur["threads"].append(th)

new_samples = [s for s in samples if s["new"]]
old_samples = [s for s in samples if s["new"] is False]
print(f"total sample records: {len(samples)} (old-boot tail {len(old_samples)}, "
      f"this boot {len(new_samples)})")
for p, s in sorted(slides_new.items()):
    print(f"  this-boot slide: {p} = 0x{s:x}")

# census of THIS boot: per (proc,pc) with kernel fields
pc_cnt = collections.Counter()
for s in new_samples:
    for t in s["threads"]:
        pc_cnt[(t["proc"], t["pc"])] += 1

print(f"\nthis-boot distinct (proc,pc) census (top 15):")
for (p, pc), c in pc_cnt.most_common(15):
    slide = slides_new.get(p, 0)
    print(f"  {p:12s} pc 0x{pc:x} unslide 0x{pc - slide:x}  n={c}")

# parked-thread kernel-side detail: group by (proc, pc, st, we, wq, cont)
print(f"\nkernel-side group census (this boot, parked or not):")
grp = collections.Counter()
kbt_by_grp = {}
for s in new_samples:
    for t in s["threads"]:
        if "th" not in t:
            continue
        k = (t["proc"], hex(t["pc"]), hex(t["st"]), hex(t["we"]),
             hex(t["wq"]), hex(t["cont"]))
        grp[k] += 1
        if k not in kbt_by_grp and len(t["kbt"]) > 1:
            kbt_by_grp[k] = t["kbt"]
for k, c in grp.most_common(20):
    print(f"  n={c:<4d} {k[0]:12s} pc={k[1]} st={k[2]} we={k[3]} "
          f"wq={k[4]} cont={k[5]}")
    if k in kbt_by_grp:
        print(f"         kbt: " + " ".join(f"0x{x:x}" for x in kbt_by_grp[k]))

# distinct wq values among TH_WAIT-ish threads
wqs = collections.Counter()
for s in new_samples:
    for t in s["threads"]:
        if "th" in t and t["st"] in (0x2, 0x6, 0xa) and t["wq"]:
            wqs[(t["proc"], hex(t["wq"]))] += 1
print(f"\ndistinct nonzero wq values on waiting threads (st&2):")
for (p, wq), c in wqs.most_common(20):
    print(f"  {p:12s} wq={wq}  n={c}")

json.dump({"samples": samples, "slides_new": {p: hex(s) for p, s in slides_new.items()}},
          open("/tmp/ring30_census.json", "w"), indent=1)
print("\nwrote /tmp/ring30_census.json")

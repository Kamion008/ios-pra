#!/usr/bin/env python3
"""census29.py - parse ring29.txt sampler lines, census PCs per process/thread.
Writes /tmp/census29.json and prints a summary. Pure text parsing, no cache.
"""
import json, re, sys, collections

RING = sys.argv[1] if len(sys.argv) > 1 else "work/ring29.txt"

# SMP --- sample N
# SMP <proc>[<pid>] slide 0x<SLIDE> mh 0x<MH>
# SMP <proc> t<T> pc 0x<PC> lr 0x<LR> sp 0x<SP> bt <b1> <b2> ...
re_sample = re.compile(r"^SMP --- sample (\d+)")
re_slide  = re.compile(r"^SMP (\S+)\[(\d+)\] slide 0x([0-9a-f]+) mh 0x([0-9a-f]+)")
re_thread = re.compile(r"^SMP (\S+) t(\d+) pc 0x([0-9a-f]+) lr 0x([0-9a-f]+) sp 0x([0-9a-f]+) bt(.*)")

samples = []            # list of {n, threads: [(proc,t,pc,lr,sp,bt)]}
slides = {}             # proc -> (slide, mh, pid)
cur = None
parsed_threads = 0
for line in open(RING, errors="replace"):
    line = line.rstrip("\n")
    m = re_sample.match(line)
    if m:
        cur = {"n": int(m.group(1)), "threads": []}
        samples.append(cur)
        continue
    m = re_slide.match(line)
    if m:
        slides[m.group(1)] = (int(m.group(3), 16), int(m.group(4), 16), int(m.group(2)))
        continue
    m = re_thread.match(line)
    if m and cur is not None:
        bt = [int(x, 16) for x in m.group(6).split() if re.fullmatch(r"0x[0-9a-f]+", x)]
        cur["threads"].append({
            "proc": m.group(1), "t": int(m.group(2)),
            "pc": int(m.group(3), 16), "lr": int(m.group(4), 16),
            "sp": int(m.group(5), 16), "bt": bt})
        parsed_threads += 1

# census: per (proc, pc) counts; per (proc, t) thread count; distinct pc overall
pc_cnt   = collections.Counter()
thr_cnt  = collections.Counter()
proc_slides = {}
for s in samples:
    for th in s["threads"]:
        pc_cnt[(th["proc"], th["pc"])] += 1
        thr_cnt[(th["proc"], th["t"])] += 1

out = {
    "n_samples": len(samples),
    "n_threads_parsed": parsed_threads,
    "slides": {p: {"slide": hex(s[0]), "mh": hex(s[1]), "pid": s[2]} for p, s in slides.items()},
    "pc_census": [
        {"proc": p, "pc": hex(pc), "count": c, "unslide": hex(pc - slides[p][0])}
        for (p, pc), c in pc_cnt.most_common()],
    "thread_census": {f"{p} t{t}": c for (p, t), c in thr_cnt.most_common()},
}
json.dump(out, open("/tmp/census29.json", "w"), indent=1)

print(f"samples={len(samples)} threads_parsed={parsed_threads}")
for p, (s, mh, pid) in sorted(slides.items()):
    print(f"slide {p}[{pid}] slide=0x{s:x} mh=0x{mh:x}")
print(f"distinct (proc,pc) pairs: {len(pc_cnt)}")
for (p, pc), c in pc_cnt.most_common():
    u = pc - slides[p][0]
    print(f"  {p:12s} pc 0x{pc:x} unslide 0x{u:x}  count {c}")
print("threads per (proc,t):")
for (p, t), c in sorted(thr_cnt.items()):
    print(f"  {p:12s} t{t:<3d} samples {c}")

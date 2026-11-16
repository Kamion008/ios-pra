#!/usr/bin/env python3
"""ringparse.py - robust parser for 0173-format SMP lines. Handles:
- glued/cut records (0166 chunk drops): records are split on 'SMP ' boundaries
- multi-boot fragments: classify per RECORD by the slide line that precedes it
- any number of processes; prints per-(slide,pid) task summaries, per-thread
  parks (>=2 sightings), kernel-side field census, PRA MSG chronology tail.
Usage: python3 -I work/ringparse.py /tmp/ring31.txt [slide-to-focus]
"""
import re, sys, collections

RING = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ring31.txt"
FOCUS = sys.argv[2] if len(sys.argv) > 2 else None

re_sample = re.compile(r"^SMP --- sample (\d+)")
re_slide  = re.compile(r"^SMP (\S+)\[(\d+)\] slide 0x([0-9a-f]+) mh 0x([0-9a-f]+)")
re_thread = re.compile(
    r"^SMP (\S+) t(\d+) pc 0x([0-9a-f]+) lr 0x([0-9a-f]+) sp 0x([0-9a-f]+)")
re_th = re.compile(
    r"th=0x([0-9a-f]+) st=0x([0-9a-f]+) we=0x([0-9a-f]+) wq=0x([0-9a-f]+) "
    r"cont=0x([0-9a-f]+) kbt(.*)")
STUBS = {0x1c2611030: "mach_msg2", 0x1c26114f0: "workq_kernreturn",
         0x1c2611ad0: "sys_ulock_wait", 0x1c2611538: "kevent_id"}

records = []          # (slide, pid, proc, t, pc, st, we, wq, cont, kbt, sample)
slides = {}
cur_slide = cur_pid = None
cur_sample = None
for line in open(RING, errors="replace"):
    # a physical line can carry glued records: split on 'SMP ' boundaries
    for chunk in re.split(r"(?=SMP )", line.rstrip("\n")):
        if not chunk.startswith("SMP "):
            continue
        m = re_sample.match(chunk)
        if m:
            cur_sample = int(m.group(1))
            continue
        m = re_slide.match(chunk)
        if m:
            cur_slide, cur_pid = m.group(3), int(m.group(2))
            slides.setdefault((m.group(1), cur_pid, cur_slide), 0)
            slides[(m.group(1), cur_pid, cur_slide)] += 1
            continue
        m = re_thread.match(chunk)
        if m and cur_slide:
            rec = {"slide": cur_slide, "pid": cur_pid, "proc": m.group(1),
                   "t": int(m.group(2)), "pc": int(m.group(3), 16),
                   "sample": cur_sample}
            m2 = re_th.search(chunk)
            if m2:
                rec.update(th=int(m2.group(1), 16), st=int(m2.group(2), 16),
                           we=int(m2.group(3), 16), wq=int(m2.group(4), 16),
                           cont=int(m2.group(5), 16))
                rec["kbt"] = [int(x, 16) for x in m2.group(6).split()
                              if re.fullmatch(r"0x[0-9a-f]+", x)]
            records.append(rec)

print(f"records: {len(records)}")
print("== task fragments (proc, pid, slide) x sample-lines:")
for (p, pid, sl), n in sorted(slides.items(), key=lambda kv: -kv[1]):
    print(f"  {p:14s}[{pid}] slide 0x{sl}  {n} thread-lines")

def stub_name(pc, slide):
    u = pc - int(slide, 16)
    return STUBS.get(u, f"0x{u:x}")

# group by task fragment; per-thread park census
groups = collections.defaultdict(list)
for r in records:
    if FOCUS and r["slide"] != FOCUS:
        continue
    groups[(r["slide"], r["pid"], r["proc"])].append(r)

for k, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    thr = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rs:
        if "th" in r:
            thr[hex(r["th"])][stub_name(r["pc"], k[0])].append(
                (hex(r["st"]), hex(r["we"]), hex(r["wq"]), hex(r["cont"])))
    print(f"\n== {k[2]}[{k[1]}] slide 0x{k[0]}: {len(rs)} records, "
          f"{len(thr)} threads with fields")
    for th, pcs in thr.items():
        total = sum(len(v) for v in pcs.values())
        if total < 2:
            continue
        for pc, vals in pcs.items():
            sts = collections.Counter(v[0] for v in vals)
            wqs = collections.Counter(v[2] for v in vals)
            conts = collections.Counter(v[3] for v in vals)
            print(f"  th={th} n={total} pc={pc}: st={dict(sts)} "
                  f"wq_uniq={len(wqs)} top_wq={wqs.most_common(1)[0][0] if wqs else '-'} "
                  f"cont={dict(conts)}")
    # single-sighting threads with unusual state (TH_UNINT etc.)
    odd = [(hex(r["th"]), r) for r in rs if "th" in r
           and (r["st"] & 0x8)]
    for th, r in odd:
        print(f"  UNINT th={th} t{r['t']} pc={hex(r['pc'])} st={hex(r['st'])} "
              f"we={hex(r.get('we',0))} wq={hex(r.get('wq',0))} "
              f"cont={hex(r.get('cont',0))} sample={r['sample']}")

# PRA MSG tail
msgs = []
for line in open(RING, errors="replace"):
    m = re.search(r"PRA MSG\[(\d+)\]: (\S+) -> (\S+) id=(\S+)", line)
    if m:
        msgs.append((int(m.group(1)), m.group(2), m.group(3), m.group(4)))
print(f"\n== PRA MSG records: {len(msgs)}, last 8:")
for n, s, r_, i in msgs[-8:]:
    print(f"  [{n}] {s} -> {r_} id={i}")

# ---- trust-filtered park census (records matching the full format; a park
# is trusted when the SAME (th,pc,st,we,wq,cont) shape repeats >=3 times -
# systematic glue artifacts do not recur identically as churn shifts) ----
FULL = re.compile(
    r"^SMP (\S+) t(\d+) pc 0x([0-9a-f]+) lr 0x([0-9a-f]+) sp 0x([0-9a-f]+) "
    r"bt(?: 0x[0-9a-f]+){1,16} th=0x([0-9a-f]+) st=0x([0-9a-f]+) "
    r"we=0x([0-9a-f]+) wq=0x([0-9a-f]+) cont=0x([0-9a-f]+) kbt(?: 0x[0-9a-f]+)*$")
cur_slide2 = None
ok, suspect = [], 0
for line in open(RING, errors="replace"):
    for chunk in re.split(r"(?=SMP )", line.rstrip("\n")):
        m = re_slide.match(chunk)
        if m:
            cur_slide2 = m.group(3)
            continue
        m = FULL.match(chunk)
        if m and cur_slide2:
            th, st, we, wq, cont = (int(m.group(i), 16) for i in range(6, 11))
            ok.append((cur_slide2, m.group(1), hex(th), hex(int(m.group(3), 16)),
                       hex(st), hex(we), hex(wq), hex(cont)))
        elif chunk.startswith("SMP ") and " th=0x" in chunk:
            suspect += 1
print(f"\n== trust-filtered: {len(ok)} full-format records, {suspect} cut/glued")
thr2 = collections.defaultdict(collections.Counter)
for slide, proc, th, pc, st, we, wq, cont in ok:
    u = int(pc, 16) - int(slide, 16)
    name = STUBS.get(u, f"0x{u:x}")
    thr2[(slide, proc, th)][(name, st, we, wq, cont)] += 1
for k, ctr in thr2.items():
    for (name, st, we, wq, cont), n in ctr.items():
        if n >= 3:
            print(f"  PARK slide=0x{k[0]} {k[1]:12s} th={k[2]} n={n} {name} "
                  f"st={st} we={we} wq={wq} cont={cont}")

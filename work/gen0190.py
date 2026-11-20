#!/usr/bin/env python3
"""gen0190.py - build xnu/patches/0190-pra-touch-input-poll.patch.

Base: work/ci190/post0189/xnu = work/ci189/pre0189/xnu (the post-0188
reconstruction) + the 0189 patch applied; 0190 touches bsd/dev/pra_touch.c.

BOOT T13 (ring54): the 0189 length poll passed - the descriptor came
back on the FIRST attempt (32 bytes, hdr=0x20, bcd=0x100), app mode was
confirmed, the worker parsed 42 real reports, and 9 contacts were
injected through sweet_hid_touch with real coordinates. The UI still
did not react.

The worker's read gate was the 1 Hz heartbeat: idle_level is 0 (the pad
is stuck LOW - T11-T13 histograms irq lo/hi = N/0) and level never
differs, so the level branch never fires. T13 measured ~1 Hz of input.

0190: with pra_live && input_reg, read EVERY worker tick (10 ms) - the
vendor's IRQ-rate read with the stuck line replaced by polling. The
input read (2-byte length word; 0/2 = nothing pending; payload when
data) and the 1 s error backoff are unchanged. One new line proves the
mode: 'PRA touch: input poll every %u ms (the INT line is stuck LOW)'.
"""
import difflib
import os
import shutil
import subprocess
import tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci190/post0189/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0190-pra-touch-input-poll.patch"
TARGET = "bsd/dev/pra_touch.c"


def read(path):
    return open(path, encoding="utf-8").read().splitlines()


def find_one(lines, pred, tag):
    hits = [i for i, line in enumerate(lines) if pred(line)]
    assert len(hits) == 1, f"{tag}: {len(hits)} hits"
    return hits[0]


pt = read(f"{BASE}/{TARGET}")
log = []

# [1] drop the 1 Hz heartbeat state - the poll is every tick now
i_hb = find_one(pt, lambda line: line.strip() == "uint64_t last_heartbeat = 0;",
                "[1] last_heartbeat declaration")
del pt[i_hb]
log.append(f"[1] last_heartbeat declaration removed: line {i_hb + 1}")

# [2] the one-time poll-mode marker flag
i_bo = find_one(pt, lambda line: line.strip() == "unsigned backoff = 0;",
                "[2] backoff declaration")
pt.insert(i_bo + 1,
          "\tstatic bool poll_announced;   /* 0190: the poll-mode line once */")
log.append(f"[2] poll_announced declared after line {i_bo + 1}")

# [3] replace the stale level/heartbeat comment + gate with the poll
i_cmt = find_one(pt, lambda line: "Reads happen when the line differs" in line,
                 "[3] the old comment")
i_start = i_cmt - 1
assert pt[i_start].strip() == "/*", "[3] no comment opener"
i_gate = find_one(pt, lambda line: line.strip() == "do_read = false;",
                  "[3] the gate")
assert i_gate > i_cmt, "[3] gate not after the comment"
i_open = i_gate + 1
assert pt[i_open].strip() == "if (pra_live && input_reg != 0) {", \
    f"[3] unexpected gate open: {pt[i_open]!r}"
depth = 0
i_close = None
for j in range(i_open, len(pt)):
    depth += pt[j].count("{") - pt[j].count("}")
    if depth == 0:
        i_close = j
        break
assert i_close is not None, "[3] no closing brace"
assert pt[i_close - 1].strip() == "}", "[3] unexpected gate tail"

NEW_GATE = [
    '\t\t/*',
    '\t\t * 0190: read EVERY worker tick (10 ms). The pad is stuck',
    '\t\t * LOW on this board (T11-T13: irq lo/hi = N/0), so the',
    '\t\t * old level-diff gate never fired and the 1 Hz heartbeat',
    '\t\t * sampled the panel at ~1 Hz (T13: 42 reports over ~50 s)',
    '\t\t * - far too coarse for a gesture. The input read is a',
    '\t\t * 2-byte length word, with the payload only when data is',
    '\t\t * pending; at 10 ms this is the vendor\'s IRQ-rate read',
    '\t\t * with the stuck INT line replaced by polling. Every',
    '\t\t * error still backs reads off for 1 s, so a dead bus',
    '\t\t * costs at most a handful of bounded transactions per',
    '\t\t * second.',
    '\t\t */',
    '\t\tdo_read = false;',
    '\t\tif (pra_live && input_reg != 0) {',
    '\t\t\tdo_read = true;',
    '\t\t\tif (!poll_announced) {',
    '\t\t\t\tpoll_announced = true;',
    '\t\t\t\tprintf("PRA touch: input poll every %u ms "',
    '\t\t\t\t    "(the INT line is stuck LOW)\\n",',
    '\t\t\t\t    (unsigned)((tick * 1000u) / (unsigned)hz));',
    '\t\t\t}',
    '\t\t}',
]
pt = pt[:i_start] + NEW_GATE + pt[i_close + 1:]
log.append(f"[3] comment+gate replaced: lines {i_start + 1}..{i_close + 1}")

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0190 - the touch INPUT poll every worker tick (the end of the 1 Hz gate)

Boot T13 (ring54, fresh [512, 161280) = 160,768 B / 2,795 lines) +
the vendor read model (work/rvr/cyttsp5/): the 0189 length poll
PASSED - the descriptor came back on the FIRST attempt (32 bytes,
hdr=0x20, bcd=0x100), app mode was confirmed (input reg 0x3,
max_input 254), the worker parsed 42 real reports, and 9 contacts
were injected through sweet_hid_touch with real coordinates. The
user's touches reached the driver; the UI still did not react.

The worker's read gate was the 1 Hz heartbeat: idle_level is sampled
0 at probe (the pad is stuck LOW - T11-T13 histograms irq lo/hi =
1000/0, 2000/0, ..., 62500/0) and level never differs, so the level
branch never fires. T13 measured the result: 42 reports over ~50 s
(~1 Hz) - far too coarse for a swipe or a tap sequence.

This patch (0190):
1. With pra_live && input_reg != 0, do_read is set EVERY worker tick
   (10 ms) - the vendor's IRQ-rate read with the stuck INT line
   replaced by polling. The input read (2-byte length word; 0 or 2 =
   nothing pending; then the payload) and the 1 s error backoff are
   unchanged.
2. One new line at the first poll: 'PRA touch: input poll every
   %u ms (the INT line is stuck LOW)' - the marker and the proof the
   new mode is live.
3. The now-dead last_heartbeat state is removed.

Decodes (the next pratouchreset=1 boot): the poll line prints once;
a finger down should raise reports by ~10/s and print dense SWEET HID
down/up lines. Dense reports + the UI still ignoring = the
SweetHID-delivery/AKS rung (the input side is proven); reports still
at ~1/s = the IC's own cadence (unlikely).

Marker asserted in CI (direct yml commit): 'PRA touch: input poll'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for line in log:
    print("  " + line)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0190")
fp = os.path.join(scratch, TARGET)
os.makedirs(os.path.dirname(fp), exist_ok=True)
open(fp, "w").write("\n".join(read(f"{BASE}/{TARGET}")) + "\n")
subprocess.run(["git", "init", "-q", scratch], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.email", "v@v"],
               check=True)
subprocess.run(["git", "-C", scratch, "config", "user.name", "v"],
               check=True)
subprocess.run(["git", "-C", scratch, "add", "-A"], check=True)
subprocess.run(["git", "-C", scratch, "commit", "-qm", "base"], check=True)
r0 = subprocess.run(["git", "-C", scratch, "apply", "--check", "-v", OUT],
                    capture_output=True, text=True)
print(f"[verify] git apply --check rc={r0.returncode}")
assert r0.returncode == 0 and "Skipped" not in (r0.stdout + r0.stderr)
r2 = subprocess.run(["patch", "-p1", "--fuzz=0", "--dry-run", "-i", OUT],
                    cwd=scratch, capture_output=True, text=True)
print(f"[verify] GNU patch --fuzz=0 --dry-run rc={r2.returncode}")
assert r2.returncode == 0, r2.stdout + r2.stderr
r = subprocess.run(["git", "-C", scratch, "apply", "-v", OUT],
                   capture_output=True, text=True)
print(f"[verify] git apply rc={r.returncode}")
assert r.returncode == 0 and "Skipped" not in (r.stdout + r.stderr)
got = open(os.path.join(scratch, TARGET)).read()
assert got == "\n".join(pt) + "\n", "pra_touch.c mismatch"
print("[verify] pra_touch.c: applied == expected")

# structural assertions
scan = "\n".join(pt)
assert scan.count("last_heartbeat") == 0, "the 1 Hz state is gone"
assert scan.count("PRA touch: input poll every %u ms") == 1, \
    "the poll line once"
assert scan.count("static bool poll_announced;") == 1, "the flag once"
assert scan.count("(uint32_t)idle_level != level") == 0, \
    "the level gate is gone"
assert "Reads happen when the line differs" not in scan, \
    "the stale comment is gone"
i_gate = scan.index("if (pra_live && input_reg != 0) {")
i_read = scan.index("do_read = true;", i_gate)
i_backoff = scan.index("if (do_read && backoff == 0)")
assert i_gate < i_read < i_backoff, "gate < poll < backoff"
i_ann = scan.index("if (!poll_announced) {")
assert i_read < i_ann, "the poll line follows the do_read"
assert scan.count("pra_touch_input_read") == \
    "\n".join(read(f"{BASE}/{TARGET}")).count("pra_touch_input_read"), \
    "the input read untouched"
assert scan.count("pra_touch_reconcile(now, nx, ny)") == 1, \
    "the reconcile call untouched"
assert scan.count("{") == scan.count("}"), "brace balance"
print("[verify] structural assertions PASS (every-tick poll, marker, "
      "1 Hz state gone, braces)")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0190 applies to the reconstructed post-0189 base")

#!/usr/bin/env python3
"""gen0195.py - build xnu/patches/0195-pra-touch-selftest.patch.

T18 (0194, ring59) reached SpringBoard, the probe printed
`app mode confirmed, input reg 0x3 max_input=254`, and the worker
printed only its first two 10 s samples: `reports=0 errs=0 corrupt=0`.
There was no `PRA touch: hid inject` and no `SWEET HID: touch` line at
all, so 0194's panel clamp was never reached.  The ring cannot tell
whether the worker stopped/blocked after 20 s or the IC returned
`nothing pending` on every read, because the driver only logs when a
counter moves.

0195 is the instrument, not another blind touch test:

1. pra_touch.c: with `pratouchdbg=1`, print the 10 s telemetry line on
   every sample and add `reads` (input reads attempted) and `last_len`
   (the IC's last length-word response, 0 = nothing pending).  A
   continuing heartbeat proves the worker is alive; a frozen `reads`
   proves it is blocked; `reads` climbing with `last_len=0` proves the
   worker is polling a silent IC.
2. SweetHID.cpp: behind `pratouchselftest=1`, a one-shot synthetic
   touch at the OUT-OF-BOUNDS raw point 2000,3000 (down and up), fired
   from the user client after the touch queue is mapped.  It bypasses
   pra_touch and the IC, so it forces 0194's clamp: with fPanelW/H =
   1080/1920 the touch() lines must print 1079,1919; with zeroed dims
   they print -1,-1.  An in-bounds point would not invoke the clamp.
3. IOHIDEventServiceUserClient.cpp: call the selftest after the queue
   map returns (the client state is open; the command gate is not
   held), passing _owner so the callee can verify it is the touch
   service, not SweetHIDButtons.

The base is reconstructed exactly: work/ci190/post0189 + 0190 for
pra_touch.c, work/ci193/pre0193 + 0193 + 0194 for SweetHID.cpp, and
work/ci193/pre0193 (already post-0191/0192) for the user client.
"""
import difflib
import os
import subprocess
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = f"{REPO}/xnu/patches"
BASE_PRA = f"{REPO}/work/ci190/post0189/xnu/bsd/dev/pra_touch.c"
BASE_HID = f"{REPO}/work/ci193/pre0193/xnu/iokit/Kernel/arm/hid/SweetHID.cpp"
BASE_UC = f"{REPO}/work/ci193/pre0193/xnu/iokit/Kernel/arm/hid/IOHIDEventServiceUserClient.cpp"
P190 = f"{P}/0190-pra-touch-input-poll.patch"
P193 = f"{P}/0193-pra-touch-surface-geometry.patch"
P194 = f"{P}/0194-pra-touch-panel-init.patch"
OUT = f"{P}/0195-pra-touch-selftest.patch"

PRA = "bsd/dev/pra_touch.c"
HID = "iokit/Kernel/arm/hid/SweetHID.cpp"
UC = "iokit/Kernel/arm/hid/IOHIDEventServiceUserClient.cpp"


def read(path):
    return open(path, encoding="utf-8").read().splitlines()


def save(scratch, rel, lines):
    fp = os.path.join(scratch, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, "w").write("\n".join(lines) + "\n")


def text(scratch, rel):
    return open(os.path.join(scratch, rel), encoding="utf-8").read()


def one_replace(src, old, new, tag):
    n = src.count(old)
    assert n == 1, f"{tag}: {n} occurrences"
    return src.replace(old, new, 1)


def git(scratch, *args):
    return subprocess.run(["git", "-C", scratch, *args],
                          capture_output=True, text=True)


# ---- reconstruct the post-0194 base ----
tmp = tempfile.mkdtemp(prefix="b0195")
save(tmp, PRA, read(BASE_PRA))
save(tmp, HID, read(BASE_HID))
save(tmp, UC, read(BASE_UC))
assert "SWEET HID: queue stats" in "\n".join(read(BASE_UC)), \
    "user client base is not post-0191"
assert "SWEET HID: queue notify" in "\n".join(read(BASE_UC)), \
    "user client base is not post-0192"
assert subprocess.run(["git", "init", "-q", tmp]).returncode == 0
assert git(tmp, "config", "user.email", "v@v").returncode == 0
assert git(tmp, "config", "user.name", "v").returncode == 0
assert git(tmp, "add", "-A").returncode == 0
assert git(tmp, "commit", "-qm", "pre0190").returncode == 0
for p in (P190, P193, P194):
    r = git(tmp, "apply", "-p1", p)
    assert r.returncode == 0, f"{os.path.basename(p)} did not apply: {r.stderr}"

post_p = text(tmp, PRA)
post_h = text(tmp, HID)
post_u = text(tmp, UC)
log = []

# ---- pra_touch.c: heartbeat with reads/last_len ----
p = post_p
p = one_replace(
    p,
    "\tuint32_t evt_mark, err_mark, corrupt_mark, printed = 0;\n"
    "\tunsigned backoff = 0;\n",
    "\tuint32_t evt_mark, err_mark, corrupt_mark, printed = 0;\n"
    "\tuint32_t reads_total = 0, last_len = 0;\n"
    "\tunsigned backoff = 0;\n",
    "[1] worker counters")

p = one_replace(
    p,
    "\t\t\tint error = pra_touch_input_read(buf, &len);\n\n"
    "\t\t\tif (error) {\n",
    "\t\t\tint error = pra_touch_input_read(buf, &len);\n\n"
    "\t\t\treads_total++;\n"
    "\t\t\tlast_len = len;\n"
    "\t\t\tif (error) {\n",
    "[2] read accounting")

p = one_replace(
    p,
    "\t\t/*\n"
    "\t\t * At most one line per 10 s, and only when something moved\n"
    "\t\t * (or for the first two lines, so a silent boot still\n"
    "\t\t * publishes the level histogram once).\n"
    "\t\t */\n"
    "\t\tif (loops - last_print >= loops_per_10s &&\n"
    "\t\t    ((evt_total != evt_mark) || (err_total != err_mark) ||\n"
    "\t\t    (corrupt_total != corrupt_mark) || printed < 2)) {\n",
    "\t\t/*\n"
    "\t\t * At most one line per 10 s, and only when something moved\n"
    "\t\t * (or for the first two lines, so a silent boot still\n"
    "\t\t * publishes the level histogram once). 0195: pratouchdbg=1\n"
    "\t\t * makes every 10 s sample print and adds reads/last_len, so a\n"
    "\t\t * silent IC and a dead or blocked worker are distinguishable.\n"
    "\t\t */\n"
    "\t\tif (loops - last_print >= loops_per_10s &&\n"
    "\t\t    (pra_touch_dbg || (evt_total != evt_mark) ||\n"
    "\t\t    (err_total != err_mark) || (corrupt_total != corrupt_mark) ||\n"
    "\t\t    printed < 2)) {\n",
    "[3] debug heartbeat gate")

p = one_replace(
    p,
    "\t\t\tprintf(\"PRA touch: irq lo/hi=%u/%u idle=%d reports=%u \"\n"
    "\t\t\t    \"errs=%u corrupt=%u last: slot=%d x=%d y=%d p=%d\\n\",\n"
    "\t\t\t    irq_lo, irq_hi, idle_level, evt_total, err_total,\n"
    "\t\t\t    corrupt_total,\n",
    "\t\t\tprintf(\"PRA touch: irq lo/hi=%u/%u idle=%d reports=%u \"\n"
    "\t\t\t    \"errs=%u corrupt=%u reads=%u last_len=%u \"\n"
    "\t\t\t    \"last: slot=%d x=%d y=%d p=%d\\n\",\n"
    "\t\t\t    irq_lo, irq_hi, idle_level, evt_total, err_total,\n"
    "\t\t\t    corrupt_total, reads_total, last_len,\n",
    "[4] reads/last_len in telemetry")
log.append("[1-4] pra_touch.c heartbeat: debug gate + reads/last_len")

# ---- SweetHID.cpp: one-shot selftest at queue-map time ----
h = post_h
h = one_replace(
    h,
    "static SweetHIDButtons *gSweetButtons;\n"
    "static SweetHIDTouch *gSweetTouch;\n",
    "static SweetHIDButtons *gSweetButtons;\n"
    "static SweetHIDTouch *gSweetTouch;\n"
    "static bool gSweetTouchSelfTest;\t/* 0195: pratouchselftest=1 */\n",
    "[5] selftest flag")

h = one_replace(
    h,
    "\tint native = 0;\n"
    "\tPE_parse_boot_argn(\"sweetfb_native\", &native, sizeof(native));\n",
    "\tint native = 0;\n"
    "\tuint32_t selftest = 0;\n"
    "\tPE_parse_boot_argn(\"sweetfb_native\", &native, sizeof(native));\n"
    "\tif (PE_parse_boot_argn(\"pratouchselftest\", &selftest,\n"
    "\t    sizeof(selftest)) && selftest) {\n"
    "\t\tgSweetTouchSelfTest = true;\n"
    "\t\tIOLog(\"SWEET HID: selftest armed\\n\");\n"
    "\t}\n",
    "[6] selftest boot arg")

h = one_replace(
    h,
    "extern \"C\" void\n"
    "sweet_hid_touch(int finger, int down, int x, int y)\n"
    "{\n"
    "\tif (gSweetTouch) {\n"
    "\t\tgSweetTouch->touch(finger, down != 0, x, y);\n"
    "\t}\n"
    "}\n",
    "extern \"C\" void\n"
    "sweet_hid_touch(int finger, int down, int x, int y)\n"
    "{\n"
    "\tif (gSweetTouch) {\n"
    "\t\tgSweetTouch->touch(finger, down != 0, x, y);\n"
    "\t}\n"
    "}\n"
    "\n"
    "/*\n"
    " * 0195: one-shot synthetic touch, called by the user client after the\n"
    " * touch queue is mapped. This bypasses pra_touch and the IC: it tests\n"
    " * the 0194 panel clamp and the SweetHID queue with an out-of-bounds raw\n"
    " * point (2000,3000) even when the digitizer reports nothing. The clamp\n"
    " * must turn it into 1079,1919; zeroed dims would give -1,-1. The svc\n"
    " * check keeps the SweetHIDButtons queue map from firing it.\n"
    " */\n"
    "extern \"C\" void\n"
    "sweet_hid_touch_selftest(IOHIDEventService *svc)\n"
    "{\n"
    "\tif (!gSweetTouch || svc != gSweetTouch || !gSweetTouchSelfTest) {\n"
    "\t\treturn;\n"
    "\t}\n"
    "\tgSweetTouchSelfTest = false;\n"
    "\tIOLog(\"SWEET HID: selftest raw 2000,3000\\n\");\n"
    "\tgSweetTouch->touch(0, true, 2000, 3000);\n"
    "\tgSweetTouch->touch(0, false, 2000, 3000);\n"
    "}\n",
    "[7] selftest function")
log.append("[5-7] SweetHID.cpp selftest armed at queue-map time")

# ---- IOHIDEventServiceUserClient.cpp: map hook ----
u = post_u
u = one_replace(
    u,
    "#include \"IOHIDFamilyTrace.h\"\n"
    "#include <pexpert/pexpert.h>\n",
    "#include \"IOHIDFamilyTrace.h\"\n"
    "#include <pexpert/pexpert.h>\n"
    "\n"
    "/* 0195: implemented in SweetHID.cpp; called after the touch queue map. */\n"
    "extern \"C\" void sweet_hid_touch_selftest(IOHIDEventService *svc);\n",
    "[8] user client declaration")

u = one_replace(
    u,
    "    result = _commandGate->runAction(OSMemberFunctionCast(IOCommandGate::Action, this, &IOHIDEventServiceUserClient::clientMemoryForTypeGated), options, memory);\n"
    "  \n"
    "exit:\n",
    "    result = _commandGate->runAction(OSMemberFunctionCast(IOCommandGate::Action, this, &IOHIDEventServiceUserClient::clientMemoryForTypeGated), options, memory);\n"
    "\n"
    "    /* 0195: the map returned, so the client state is open and its queue\n"
    "     * exists; run the one-shot synthetic touch outside the command gate. */\n"
    "    if (result == kIOReturnSuccess && _state == kUserClientStateOpen) {\n"
    "        sweet_hid_touch_selftest(_owner);\n"
    "    }\n"
    "  \n"
    "exit:\n",
    "[9] map hook")
log.append("[8-9] user client calls selftest after the queue map")

# ---- structural assertions ----
assert "uint32_t reads_total = 0, last_len = 0;" in p
assert "\t\t\treads_total++;\n\t\t\tlast_len = len;" in p
assert "(pra_touch_dbg || (evt_total != evt_mark)" in p
assert "\"errs=%u corrupt=%u reads=%u last_len=%u \"" in p
assert "pratouchselftest" in h
assert "gSweetTouchSelfTest" in h
assert "selftest raw 2000,3000" in h
assert "sweet_hid_touch_selftest(IOHIDEventService *svc)" in h
assert "gSweetTouch->touch(0, true, 2000, 3000);" in h
assert "gSweetTouch->touch(0, false, 2000, 3000);" in h
assert "sweet_hid_touch_selftest(_owner);" in u
assert "result == kIOReturnSuccess && _state == kUserClientStateOpen" in u
assert "extern \"C\" void sweet_hid_touch_selftest(IOHIDEventService *svc);" in u
assert "selftest" not in post_h  # 0195 adds it, the base had none
log.append("[10] structural assertions PASS (heartbeat, selftest, map hook)")

# ---- emit one multi-file patch ----
expected = {PRA: p, HID: h, UC: u}
baseline = {PRA: post_p, HID: post_h, UC: post_u}
diff = []
for rel in (PRA, HID, UC):
    diff.extend(difflib.unified_diff(
        baseline[rel].splitlines(), expected[rel].splitlines(),
        fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3, lineterm=""))

header = """pra: 0195 - touch self-test + worker heartbeat

T18 (0194, ring59) is the anchor: the boot reached SpringBoard, the probe
printed `app mode confirmed, input reg 0x3 max_input=254`, and the worker's
only two 10 s samples both carried `reports=0 errs=0 corrupt=0`. There was
no `PRA touch: hid inject` and no `SWEET HID: touch` line, so 0194's panel
clamp was never reached. The ring cannot distinguish a worker that stopped
or blocked after its first 20 s from an IC that returned "nothing pending"
on every read, because the driver only logs when a counter moves.

THIS PATCH (0195) IS THE INSTRUMENT:
1. pra_touch.c: `pratouchdbg=1` prints every 10 s telemetry sample and adds
   `reads` (input reads attempted) and `last_len` (the IC's last length-word
   response; 0 = nothing pending). A continuing heartbeat proves the worker
   is alive; a frozen `reads` proves it is blocked; `reads` climbing with
   `last_len=0` proves the worker is polling a silent IC.
2. SweetHID.cpp: behind `pratouchselftest=1`, a one-shot synthetic touch
   at the OUT-OF-BOUNDS raw point 2000,3000 (down and up), fired when the
   touch queue is mapped. It bypasses pra_touch and the IC, so it forces
   0194's clamp: with fPanelW/H = 1080/1920 touch() must print 1079,1919;
   with the old zeroed dims it prints -1,-1. An in-bounds point would not
   invoke the clamp.
3. IOHIDEventServiceUserClient.cpp: call the selftest after the queue map
   returns, when the client state is open and the command gate is not held;
   pass _owner so the callee ignores the SweetHIDButtons map.

No behavior change without the two boot args. The falsifier for T19:
selftest prints 1079,1919 = the clamp ran with 1080/1920; -1,-1 = 0194
not effective; any other value = investigate the clamp; heartbeat stops/
reads frozen = worker issue; reads climbing + last_len=0 = IC silent;
selftest clamped + queue drains but UI inert = userland routing is next.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(diff) + "\n")
print(f"[emit] wrote {OUT}")

# ---- verify three ways ----
scratch = tempfile.mkdtemp(prefix="v0195")
for rel in (PRA, HID, UC):
    save(scratch, rel, baseline[rel].splitlines())
assert subprocess.run(["git", "init", "-q", scratch]).returncode == 0
assert git(scratch, "config", "user.email", "v@v").returncode == 0
assert git(scratch, "config", "user.name", "v").returncode == 0
assert git(scratch, "add", "-A").returncode == 0
assert git(scratch, "commit", "-qm", "post0194").returncode == 0

r = git(scratch, "apply", "--check", "-p1", OUT)
print(f"[verify] git apply --check rc={r.returncode}")
assert r.returncode == 0, r.stderr
r = subprocess.run(["patch", "--fuzz=0", "--dry-run", "-p1", "-d", scratch,
                    "-i", OUT], capture_output=True, text=True)
print(f"[verify] GNU patch --fuzz=0 --dry-run rc={r.returncode}")
assert r.returncode == 0, r.stdout + r.stderr
r = git(scratch, "apply", "-p1", OUT)
print(f"[verify] git apply rc={r.returncode}")
assert r.returncode == 0, r.stderr
for rel in (PRA, HID, UC):
    applied = text(scratch, rel)
    assert applied == expected[rel], f"{rel}: applied != expected"
    print(f"[verify] {rel}: applied == expected")
print("[verify] structural assertions PASS (heartbeat, selftest, map hook)")
print("[done] VERIFY PASS: 0195 applies to post-0194 pra_touch.c + SweetHID.cpp + post-0192 user client")
for line in log:
    print("  " + line)

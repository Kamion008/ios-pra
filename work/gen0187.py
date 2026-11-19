#!/usr/bin/env python3
"""gen0187.py - build xnu/patches/0187-pra-async-desc-read.patch.

Base: the post-0186 pra_touch.c, reconstructed locally
(work/ci187/post0186 = the post-0185 reconstruction + the 0186 patch
applied; 0186 touches pra_touch.c only, verified during gen0186).

ROOT CAUSE (work/driver-bringup-research-2026-11-19.md + the vendor
sources in work/rvr/cyttsp5/ + boots T8-T10): the TT5 is a
COMMAND/RESPONSE device, not a register file. The vendor's
descriptor read (cyttsp5_core.c:2968-3010) = (1) write the 2-byte
descriptor-register request, (2) WAIT for the IC's INTERRUPT
(wait_event_timeout), (3) the response arrives via the INPUT path -
read with the PURE-READ form (cyttsp5_i2c.c:162-200: addr+R, NO
register write - the IC's default pointer IS the response buffer;
read_default_nosize reads 2 bytes = the response length then the
body). Our ladder used the SYNCHRONOUS register-file model (write
the pointer + immediately read) - the T9/T10 reads returned the
IC's fixed default-read state block (the ~28 identical bytes across
forms and boots) instead of the descriptor, because the IC never
implements a synchronous register read.

THIS PATCH: the ASYNCHRONOUS descriptor read.
1. The request: pra_touch_txn([0x01 0x00], 2, NULL, 0) - the write
   with STOP (a request, not a pointer).
2. The INT wait: poll gpio28.0 (the IC's INT line, already
   histogrammed by the worker) for a level CHANGE from the probe-
   sampled idle, bounded ~200 ms (5 ms tsleep ticks; the vendor's
   descriptor timeout class).
3. The pure read: pra_touch_txn(NULL, 0, desc, HID_DESC_SIZE) -
   the 0185 interleaved phase pushes the CMD_READs and drains (the
   T8-verified form; the scan's 1-byte pure read already ACKed on
   this bus).
The BL_LAUNCH's reset_expected = 1 (cyttsp5_core.c:2864-2867): the
IC resets itself after the launch - the sequence is issued TWICE
(the second attempt survives the reset window).

The falsifier ladder (the next pratouchreset=1 boot): the pure read
returns len=32 bcd=0x100 = app mode confirmed - pra_live=true, the
reports flow (touch!); a different length/content = the IC's mode
or the response framing rung (the BL status command next); the INT
never changing = the INT routing/polarity rung (the worker's
histogram is the cross-check).
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci187/post0186/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0187-pra-async-desc-read.patch"
TARGET = "bsd/dev/pra_touch.c"

def read(path):
    return open(path, encoding="utf-8").read().splitlines()

def anchor_unique(lines, anchor, tag):
    n = sum(1 for i in range(len(lines))
            if tuple(lines[i:i+len(anchor)]) == tuple(anchor))
    assert n == 1, f"{tag}: anchor not unique ({n} hits): {anchor[0][:60]!r}"
    return next(i for i in range(len(lines))
                if tuple(lines[i:i+len(anchor)]) == tuple(anchor))

def replace_block(lines, anchor, new, tag):
    i = anchor_unique(lines, anchor, tag)
    return lines[:i] + new + lines[i+len(anchor):], f"{tag}: replaced @ line {i+1}"

pt = read(f"{BASE}/{TARGET}")
log = []

# [1] the desc-read rewrite: the asynchronous command/response model
pt, m = replace_block(pt, [
    "/* HID descriptor: write the 16-bit LE register address 0x0001, repeated",
    " * start, read 32 bytes (see header comment for the addressing source). */",
    "static int",
    "pra_touch_desc_read(uint8_t *desc)",
    "{",
    "\tuint8_t reg[2] = {",
    "\t\t(uint8_t)(HID_DESC_REG & 0xffu),",
    "\t\t(uint8_t)(HID_DESC_REG >> 8),",
    "\t};",
    "",
    "\treturn pra_touch_txn(reg, 2, desc, HID_DESC_SIZE);",
    "}",
], [
    "/* 0187: the INT wait - the TT5 signals the response on its INT",
    " * line (gpio28.0, the pad the worker already histograms). The",
    " * vendor waits on the wait queue for the descriptor timeout",
    " * class (cyttsp5_core.c:2988-2994); we poll the pad level for a",
    " * CHANGE from the probe-sampled idle (the polarity UNKNOWN -",
    " * either direction counts), bounded ~200 ms in 5 ms tsleep",
    " * ticks. Called OUTSIDE the bus mutex (between the txns). */",
    "static unsigned pra_touch_ms_ticks(unsigned ms);   /* defined later */",
    "",
    "static int",
    "pra_touch_desc_wait_int(void)",
    "{",
    "\tunsigned waited = 0;",
    "",
    "\twhile (waited < 200u) {",
    "\t\tuint32_t dat = pra_touch_rd32(pra_gpio_regs,",
    "\t\t\t    PRA_TOUCH_IRQ_DAT_OFF) & PRA_TOUCH_IRQ_BIT;",
    "\t\tif ((int)(dat ? 1u : 0u) != idle_level) {",
    "\t\t\treturn 0;   /* the line changed: the response is ready */",
    "\t\t}",
    "\t\t(void)tsleep(&pra_touch_chan, PZERO, \"pradescw\",",
    "\t\t\t    pra_touch_ms_ticks(5u));",
    "\t\twaited += 5u;",
    "\t}",
    "\treturn ETIMEDOUT;",
    "}",
    "",
    "/* 0187: the ASYNCHRONOUS descriptor read - the TT5 is a",
    " * command/response device, not a register file (the vendor:",
    " * cyttsp5_core.c:2968-3010 writes the request, waits for the",
    " * INT, and reads the response via the default pointer;",
    " * cyttsp5_i2c.c:175+ read_default_nosize = addr+R with NO",
    " * register write). Our synchronous write-pointer+read returned",
    " * the IC's fixed default-read state block (boots T9/T10: the",
    " * ~28 identical bytes across forms). The sequence, issued",
    " * TWICE (the BL_LAUNCH's reset_expected = 1 - cyttsp5_core.c",
    " * :2864-2867: the IC resets itself after the launch, so the",
    " * second attempt survives the reset window): (1) the request",
    " * [0x01 0x00] with STOP; (2) the INT wait; (3) the PURE read -",
    " * pra_touch_txn(NULL, 0, desc, 32): the 0185 interleaved phase",
    " * pushes the CMD_READs and drains (the 0183 scan's 1-byte pure",
    " * read already ACKed on this bus). */",
    "static int",
    "pra_touch_desc_read(uint8_t *desc)",
    "{",
    "\tuint8_t req[2] = { 0x01u, 0x00u };",
    "\tint error = 0;",
    "\tint attempt;",
    "",
    "\tfor (attempt = 0; attempt < 2; attempt++) {",
    "\t\tprintf(\"PRA touch: desc attempt %d: request...\\n\",",
    "\t\t\t    attempt + 1);",
    "\t\terror = pra_touch_txn(req, 2, NULL, 0);",
    "\t\tif (error == 0) {",
    "\t\t\terror = pra_touch_desc_wait_int();",
    "\t\t}",
    "\t\tif (error == 0) {",
    "\t\t\terror = pra_touch_txn(NULL, 0, desc, HID_DESC_SIZE);",
    "\t\t}",
    "\t\tif (error == 0) {",
    "\t\t\tprintf(\"PRA touch: desc attempt %d: the response \",",
    "\t\t\t\t\"received (%u bytes)\\n\", attempt + 1,",
    "\t\t\t\t\t    (unsigned)HID_DESC_SIZE);",
    "\t\t\treturn 0;",
    "\t\t}",
    "\t\tprintf(\"PRA touch: desc attempt %d failed err=%d\\n\",",
    "\t\t\t    attempt + 1, error);",
    "\t}",
    "\treturn error;",
    "}",
], "[1] the async descriptor read")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0187 - the ASYNCHRONOUS descriptor read: the request, the INT
wait, the pure read (the TT5's command/response model)

work/driver-bringup-research-2026-11-19.md + the vendor sources
(work/rvr/cyttsp5/, fetched and verified) + boots T8-T10: the TT5 is
a COMMAND/RESPONSE device, not a register file. The vendor's
descriptor read (cyttsp5_core.c:2968-3010) = write the 2-byte
descriptor-register request, WAIT for the IC's INTERRUPT
(wait_event_timeout), then read the response via the INPUT path.
The pure read (cyttsp5_i2c.c:162-200, read_default_nosize) =
addr+R with NO register write - the IC's default pointer IS the
response buffer. Our ladder's synchronous write-pointer+read forms
(0172-0186: both the separate-STOP and the repeated-start) returned
the IC's fixed default-read state block (~28 identical bytes across
forms and boots, ring50/ring51) - the register-file model does not
exist on this silicon's HID interface.

This patch: the ASYNCHRONOUS descriptor read.
1. The request: pra_touch_txn([0x01 0x00], 2, NULL, 0) - the write
   with STOP.
2. The INT wait: poll gpio28.0 for a level CHANGE from the
   probe-sampled idle (the polarity UNKNOWN - either direction
   counts), bounded ~200 ms in 5 ms tsleep ticks, called OUTSIDE
   the bus mutex (between the txns).
3. The PURE read: pra_touch_txn(NULL, 0, desc, HID_DESC_SIZE) - the
   0185 interleaved phase pushes the CMD_READs and drains (the 0183
   scan's 1-byte pure read already ACKed on this bus - the form is
   hardware-verified).
The BL_LAUNCH's reset_expected = 1 (cyttsp5_core.c:2864-2867): the
IC resets itself after the launch - the sequence is issued TWICE
(the second attempt survives the reset window). Each attempt
prints one line.

Decodes (the next pratouchreset=1 boot): the response received and
the parse gates pass (len=32 bcd=0x100) = app mode confirmed,
pra_live=true, the reports flow (touch, at the 1 Hz heartbeat pace
until the IRQ rung); the response received but the parse fails =
the response framing rung (the length-prefix offset question -
the bytes print for the offline decode); the INT never changing =
the INT routing/polarity rung (the worker's histogram is the
cross-check); err=6 on the request = a regression against T8.

Marker asserted in CI (direct yml commit): 'PRA touch: desc
attempt'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0187")
fp = os.path.join(scratch, TARGET)
os.makedirs(os.path.dirname(fp), exist_ok=True)
open(fp, "w").write("\n".join(read(f"{BASE}/{TARGET}")) + "\n")
subprocess.run(["git", "init", "-q", scratch], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.email", "v@v"], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.name", "v"], check=True)
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
i_fn = next(i for i, l in enumerate(pt) if l.startswith("pra_touch_desc_read(uint8_t *desc)"))
i_wait = next(i for i, l in enumerate(pt) if l.startswith("pra_touch_desc_wait_int(void)"))
i_probe = next(i for i, l in enumerate(pt) if "probe-sampled idle" in l)
i_worker = next(i for i, l in enumerate(pt) if "kernel_thread_start(pra_touch_thread" in l)
assert i_wait < i_fn < i_worker, \
    f"the order: the wait helper @{i_wait+1} < desc_read @{i_fn+1} < the worker start @{i_worker+1}"
print(f"[verify] the wait helper @{i_wait+1} < desc_read @{i_fn+1} < the worker @{i_worker+1}")
scan_text = "\n".join(pt)
assert scan_text.count("pra_touch_txn(req, 2, NULL, 0)") == 1, "the request txn once"
assert scan_text.count("pra_touch_txn(NULL, 0, desc, HID_DESC_SIZE)") == 1, "the pure read once"
assert "pra_touch_desc_wait_int();" in scan_text, "the INT wait called"
assert "attempt < 2" in scan_text, "the reset_expected re-issue"
assert scan_text.count("PRA touch: desc attempt") == 3, "three print sites (two attempts + one failure)"
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0187 applies to the reconstructed post-0186 base")

#!/usr/bin/env python3
"""gen0188.py - build xnu/patches/0188-pra-touch-int-level.patch.

Base: work/ci188/pre0188/xnu = work/ci187/post0186 (the post-0186
reconstruction) + the 0187 patch applied; 0187 and 0188 touch
bsd/dev/pra_touch.c only. The base was rebuilt and verified this
session (patch -p1 --fuzz=0 clean, the 0187 marker present).

ROOT CAUSE (boot T11, ring52 + the vendor sources + the PRA fdt):
the 0187 INT wait polls gpio28.0 for a level CHANGE from the
probe-sampled idle. The baseline is sampled at probe step 3, BEFORE
the rails enable and the reset/launch (step 3.5), on an unpowered
line: 0. The vendor registers the line ACTIVE-LOW
(cyttsp5_core.c:6723-6726: IRQF_TRIGGER_LOW|ONESHOT or
IRQF_TRIGGER_FALLING), so a change from 0 means waiting for the
DEasserted level. T11's line read 0 for the whole boot (the worker:
lo/hi=2000/0), the wait timed out both attempts, and the pure read
was skipped (diag: flush=0, stat=06 = no read commands queued) -
the response framing was never tested.

THIS PATCH (0188):
1. The wait takes the LEVEL, not the change: an already-asserted
   (LOW) line is ready immediately (the vendor's level IRQ fires on
   an asserted line); a HIGH line waits for the falling edge. The
   start/end levels return for the attempt line.
2. The pure read runs UNCONDITIONALLY after a successful request -
   even when the wait times out. The line can be unreadable while
   the response sits in the IC's buffer; the read is write-free and
   its result is the real verdict.
3. The parse-failure branch prints the first 16 descriptor bytes
   (PRA touch: desc raw=...) so the framing question (a leading
   0x20/0x22 length word = the response is length-prefixed) is
   answered from the ring, not only under pratouchdbg.

Marker asserted in CI (direct yml commit): 'PRA touch: desc raw='.
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci188/pre0188/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0188-pra-touch-int-level.patch"
TARGET = "bsd/dev/pra_touch.c"


def read(path):
    return open(path, encoding="utf-8").read().splitlines()


def anchor_unique(lines, anchor, tag):
    n = sum(1 for i in range(len(lines))
            if tuple(lines[i:i + len(anchor)]) == tuple(anchor))
    assert n == 1, f"{tag}: anchor not unique ({n} hits): {anchor[0][:60]!r}"
    return next(i for i in range(len(lines))
                if tuple(lines[i:i + len(anchor)]) == tuple(anchor))


def replace_block(lines, anchor, new, tag):
    i = anchor_unique(lines, anchor, tag)
    return lines[:i] + new + lines[i + len(anchor):], f"{tag}: replaced @ line {i + 1}"


pt = read(f"{BASE}/{TARGET}")
log = []

# [1] the wait helper: the level semantics (replace the 0187 block)
pt, m = replace_block(pt, [
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
], [
    "/* 0188: the INT LEVEL semantics (boot T11, ring52). The vendor",
    " * registers the line ACTIVE-LOW (cyttsp5_core.c:6723-6726:",
    " * IRQF_TRIGGER_LOW|IRQF_ONESHOT or IRQF_TRIGGER_FALLING): the",
    " * line idles HIGH and ASSERTS LOW. The 0187 wait required a",
    " * level DIFFERING from the probe-sampled idle - but that",
    " * baseline was sampled BEFORE the rails and the reset (step 3",
    " * vs step 3.5) on an unpowered line: 0. A change from 0 is the",
    " * DEasserted level, and T11's line read 0 for the whole boot",
    " * (the worker's histogram: 2000 low / 0 high), so both waits",
    " * timed out and the pure read never ran (the diag: flush=0,",
    " * stat=06). The wait now takes the level: an already-asserted",
    " * (LOW) line is ready NOW (the vendor's level IRQ fires on an",
    " * asserted line), a HIGH line waits for the falling edge. The",
    " * start/end levels return for the attempt line (the trail).",
    " * Called OUTSIDE the bus mutex (between the txns). */",
    "#define PRA_TOUCH_IRQ_ASSERTED  0u",
    "",
    "static unsigned pra_touch_ms_ticks(unsigned ms);   /* defined later */",
    "",
    "static int",
    "pra_touch_desc_wait_int(unsigned *start, unsigned *end)",
    "{",
    "\tunsigned waited = 0;",
    "",
    "\t*start = pra_touch_rd32(pra_gpio_regs, PRA_TOUCH_IRQ_DAT_OFF) &",
    "\t    PRA_TOUCH_IRQ_BIT;",
    "\t*end = *start;",
    "\twhile (waited < 200u) {",
    "\t\tunsigned dat = pra_touch_rd32(pra_gpio_regs,",
    "\t\t    PRA_TOUCH_IRQ_DAT_OFF) & PRA_TOUCH_IRQ_BIT;",
    "\t\tif (dat == PRA_TOUCH_IRQ_ASSERTED) {",
    "\t\t\t*end = dat;",
    "\t\t\treturn 0;   /* asserted: the response is ready */",
    "\t\t}",
    "\t\t*end = dat;",
    "\t\t(void)tsleep(&pra_touch_chan, PZERO, \"pradescw\",",
    "\t\t    pra_touch_ms_ticks(5u));",
    "\t\twaited += 5u;",
    "\t}",
    "\treturn ETIMEDOUT;",
    "}",
], "[1] the level-semantics wait")
log.append(m)

# [2] the desc read: the unconditional pure read + the irq trail
pt, m = replace_block(pt, [
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
], [
    "/* 0188: the ASYNCHRONOUS descriptor read (the 0187 model: the",
    " * vendor's cyttsp5_core.c:2968-3010 = request, wait, response;",
    " * the pure read = cyttsp5_i2c.c:175+ read_default_nosize)",
    " * with the T11 fixes: the wait's LEVEL semantics (above) and",
    " * the pure read issued UNCONDITIONALLY after a successful",
    " * request - the T11 wait's timeout skipped the read, so the",
    " * response framing was never tested; the line can be",
    " * unreadable (stuck/misrouted) while the response sits in the",
    " * IC's buffer, and the read is write-free. Issued TWICE (the",
    " * BL_LAUNCH's reset_expected = 1 - cyttsp5_core.c:2864-2867).",
    " * Each attempt prints its irq start/end levels. */",
    "static int",
    "pra_touch_desc_read(uint8_t *desc)",
    "{",
    "\tuint8_t req[2] = { 0x01u, 0x00u };",
    "\tint error = 0;",
    "\tint attempt;",
    "",
    "\tfor (attempt = 0; attempt < 2; attempt++) {",
    "\t\tunsigned irq_start = 0, irq_end = 0;",
    "\t\tint waited = 0, wait_error = 0;",
    "",
    "\t\tprintf(\"PRA touch: desc attempt %d: request...\\n\",",
    "\t\t\t    attempt + 1);",
    "\t\terror = pra_touch_txn(req, 2, NULL, 0);",
    "\t\tif (error == 0) {",
    "\t\t\twaited = 1;",
    "\t\t\twait_error = pra_touch_desc_wait_int(&irq_start,",
    "\t\t\t    &irq_end);",
    "\t\t\terror = pra_touch_txn(NULL, 0, desc, HID_DESC_SIZE);",
    "\t\t}",
    "\t\tif (error == 0) {",
    "\t\t\tprintf(\"PRA touch: desc attempt %d: the response \",",
    "\t\t\t\t\"received (%u bytes), irq %u->%u%s\\n\",",
    "\t\t\t\t    attempt + 1, (unsigned)HID_DESC_SIZE,",
    "\t\t\t\t    irq_start, irq_end, wait_error ?",
    "\t\t\t\t    \", read past a wait timeout\" : \"\");",
    "\t\t\treturn 0;",
    "\t\t}",
    "\t\tif (waited) {",
    "\t\t\tprintf(\"PRA touch: desc attempt %d failed err=%d \"",
    "\t\t\t    \"(irq %u->%u, wait=%s)\\n\", attempt + 1, error,",
    "\t\t\t    irq_start, irq_end,",
    "\t\t\t    wait_error ? \"timeout\" : \"asserted\");",
    "\t\t} else {",
    "\t\t\tprintf(\"PRA touch: desc attempt %d failed err=%d \"",
    "\t\t\t    \"(the request)\\n\", attempt + 1, error);",
    "\t\t}",
    "\t}",
    "\treturn error;",
    "}",
], "[2] the unconditional read")
log.append(m)

# [3] the framing trail: the raw bytes on every failed parse
pt, m = replace_block(pt, [
    "\t\t} else {",
    "\t\t\tprintf(\"PRA touch: descriptor invalid (len=%u \"",
    "\t\t\t    \"bcd=%#x), touch reads disabled\\n\", dlen, bcd);",
    "\t\t}",
], [
    "\t\t} else {",
    "\t\t\tprintf(\"PRA touch: descriptor invalid (len=%u \"",
    "\t\t\t    \"bcd=%#x), touch reads disabled\\n\", dlen, bcd);",
    "\t\t\t/* 0188: the framing trail - the first 16 bytes print",
    "\t\t\t * on EVERY failed parse (not only under pratouchdbg):",
    "\t\t\t * a leading 0x20/0x22 word = the response is",
    "\t\t\t * length-prefixed (the HID input-read framing) and",
    "\t\t\t * the parse offset is the next fix. */",
    "\t\t\tprintf(\"PRA touch: desc raw=%02x %02x %02x %02x \"",
    "\t\t\t    \"%02x %02x %02x %02x %02x %02x %02x %02x \"",
    "\t\t\t    \"%02x %02x %02x %02x\\n\", desc[0], desc[1],",
    "\t\t\t    desc[2], desc[3], desc[4], desc[5], desc[6],",
    "\t\t\t    desc[7], desc[8], desc[9], desc[10], desc[11],",
    "\t\t\t    desc[12], desc[13], desc[14], desc[15]);",
    "\t\t}",
], "[3] the framing trail")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0188 - the INT LEVEL semantics + the unconditional pure read
(the T11 wait-timeout-before-read fix)

Boot T11 (ring52, fresh [512, 252416) = 246.0 KiB) + the vendor
sources (work/rvr/cyttsp5/) + the PRA's real fdt
(research/pra-artifacts/twrp-golden/fdt.bin): the 0187 INT wait
required a level CHANGE from the probe-sampled idle. The baseline
is sampled at probe step 3, BEFORE the rails enable and the
reset/launch (step 3.5), on an unpowered line: 0. The vendor
registers the line ACTIVE-LOW (cyttsp5_core.c:6723-6726:
IRQF_TRIGGER_LOW|IRQF_ONESHOT or IRQF_TRIGGER_FALLING), so a change
from 0 is the DEasserted level. T11's line read 0 for the whole
boot (the worker's histogram: 2000 low / 0 high), both waits timed
out, and the pure read was never issued (the diag: flush=0,
stat=06 = no read commands queued) - the response framing was never
tested. The fdt confirms the wiring is right: cy,irq_gpio =
<&gpio@fff1d000 0 0> (phandle 0x68) and cy,rst_gpio =
<&gpio@e8a1d000 1 0> (phandle 0x69) - the port's two bases.

This patch (0188):
1. The wait takes the LEVEL, not the change: an already-asserted
   (LOW) line is ready immediately (the vendor's level IRQ fires on
   an asserted line); a HIGH line waits for the falling edge. The
   start/end levels return for the attempt line.
2. The pure read runs UNCONDITIONALLY after a successful request -
   even when the wait times out. The line can be unreadable while
   the response sits in the IC's buffer; the read is write-free and
   its result is the real verdict.
3. The parse-failure branch prints the first 16 descriptor bytes
   (PRA touch: desc raw=...) - the framing question (a leading
   0x20/0x22 length word = the response is length-prefixed) is
   answered from the ring.

Decodes (the next pratouchreset=1 boot): the read returns 32 bytes
and the parse passes (len=32 bcd=0x100) = app mode confirmed,
pra_live=true, the reports flow; the read returns bytes and the
parse fails = the FRAMING rung (the raw line answers the offset);
the read err=60 with flush>0/stat activity = the IC sent nothing
(the mode/bus rung); err=6 = a regression against T8-T10; the
attempt line's irq 1->1 = the line never asserts (routing/polarity
beyond the driver), 0->0 = already asserted (the read decides).

Marker asserted in CI (direct yml commit): 'PRA touch: desc raw='.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0188")
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
i_wait = next(i for i, l in enumerate(pt) if l.startswith("pra_touch_desc_wait_int(unsigned *start"))
i_fn = next(i for i, l in enumerate(pt) if l.startswith("pra_touch_desc_read(uint8_t *desc)"))
i_worker = next(i for i, l in enumerate(pt) if "kernel_thread_start(pra_touch_thread" in l)
assert i_wait < i_fn < i_worker, \
    f"the order: the wait helper @{i_wait+1} < desc_read @{i_fn+1} < the worker start @{i_worker+1}"
print(f"[verify] the wait helper @{i_wait+1} < desc_read @{i_fn+1} < the worker @{i_worker+1}")
scan_text = "\n".join(pt)
assert scan_text.count("pra_touch_txn(req, 2, NULL, 0)") == 1, "the request txn once"
assert scan_text.count("pra_touch_txn(NULL, 0, desc, HID_DESC_SIZE)") == 1, \
    "the pure read once, outside every error gate"
assert "wait_error = pra_touch_desc_wait_int(&irq_start," in scan_text, "the wait binds levels"
assert "dat == PRA_TOUCH_IRQ_ASSERTED" in scan_text, "the level comparison"
assert scan_text.count("#define PRA_TOUCH_IRQ_ASSERTED") == 1, "the asserted constant once"
assert scan_text.count("PRA touch: desc raw=%02x") == 1, "the framing trail once"
# the read must NOT be gated on the wait: the line after the wait call is the read
i_cw = scan_text.index("pra_touch_desc_wait_int(&irq_start,")
i_cr = scan_text.index("pra_touch_txn(NULL, 0, desc, HID_DESC_SIZE)")
assert i_cw < i_cr and "error == 0" not in scan_text[i_cw:i_cr], \
    "the read is not gated on the wait result"
# brace balance (the naive count; the compiler is the real oracle)
assert scan_text.count("{") == scan_text.count("}"), "brace balance"
print("[verify] structural assertions PASS (order, txn counts, ungated read, braces)")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0188 applies to the reconstructed post-0187 base")

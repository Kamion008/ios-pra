#!/usr/bin/env python3
"""gen0185.py v2 - build xnu/patches/0185-pra-i2c-read-path.patch.

Base: the post-0184 pra_touch.c, reconstructed locally
(work/ci185/post0184 = the post-0183 reconstruction + the 0184 patch
applied; 0184 touches pra_touch.c only, verified during gen0184).

ROOT CAUSE (boot T8, ring49): the bring-up replication WORKED - the
scan ACKed [1c] (the only device on the bus), and BL_LAUNCH_APP was
SENT (err=0, crc=0xc720) - the first successful I2C transactions in
the project's history. The descriptor read then failed err=60
(ETIMEDOUT) with abrt=none, flush=0 - EXACTLY the predicted CMD_READ
latent bug: pra_i2c_xfer never pushes read commands (the read loop
only pops the RX FIFO), so no data can ever clock in - a "read" was
just the 2-byte register-address write with an empty RX FIFO.

THIS PATCH (v2 - the round-1 K4 FAULT fixed: the read phase is
INTERLEAVED - push one read command, drain one byte - because the
RX FIFO is 64 entries and the report reads run up to 128 bytes; a
push-all-then-drain form overflows above 64):
1. The write phase ALWAYS ends with STOP (the vendor's wire shape -
   the write transaction terminates).
2. The interleaved read phase: per byte - TXFLR-gated push of ONE
   CMD_READ (STOP on the last), then a bounded wait for the byte,
   then pop. Any rlen works; the existing drain loop stays as the
   no-op safety net. The scan is unaffected (its read commands are
   pushed inline); the BL write (rlen=0) is byte-identical.
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci185/post0184/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0185-pra-i2c-read-path.patch"
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

# [1] the write phase always ends with STOP
pt, m = replace_block(pt, [
    "\t\t\t/* 0177: write-only transaction (BL frame) - STOP on the",
    "\t\t\t * last byte. Read transactions keep the 0172 form: STOP",
    "\t\t\t * rides the last read byte. */",
    "\t\t\tif (rlen == 0 && pushed == wlen) {",
    "\t\t\t\tcmd |= DW_IC_CMD_STOP;",
    "\t\t\t}",
], [
    "\t\t\t/* 0185: the write phase ALWAYS ends with STOP - the",
    "\t\t\t * read transaction starts fresh (the vendor's wire",
    "\t\t\t * shape; the repeated-start form never ran on this",
    "\t\t\t * hardware - the read commands were never pushed at",
    "\t\t\t * all before 0185, so neither form was proven: this",
    "\t\t\t * patch tests the simpler one, and the falsifier",
    "\t\t\t * ladder covers both outcomes). */",
    "\t\t\tif (pushed == wlen) {",
    "\t\t\t\tcmd |= DW_IC_CMD_STOP;",
    "\t\t\t}",
], "[1] the write-phase STOP")
log.append(m)

# [2] the interleaved read phase between the write loop and the drain
pt, m = replace_block(pt, [
    "\t}",
    "",
    "\twhile (error == 0 && got < rlen) {",
], [
    "\t}",
    "",
    "\t/* 0185: the read phase - push ONE read command, drain ONE",
    "\t * byte, repeat (the INTERLEAVED form): the write phase's STOP",
    "\t * terminates the write transaction and each CMD_READ runs a",
    "\t * fresh START+addr+R+byte+STOP. The 0172-0184 code never",
    "\t * pushed read commands - no data could ever clock in (the",
    "\t * err=60 signature, boot T8's desc read with abrt=none).",
    "\t * Interleaved, NOT push-all-then-drain: the RX FIFO is 64",
    "\t * entries and the report reads run up to 128 bytes - the",
    "\t * push-all form overflows above 64 (the round-1 K4 FAULT). */",
    "\tif (error == 0 && rlen > 0) {",
    "\t\tunsigned cmd_pushed = 0;",
    "\t\twhile (error == 0 && cmd_pushed < rlen) {",
    "\t\t\tbool room = false;",
    "\t\t\tfor (unsigned i = 0; i < PRA_I2C_POLLS; i++) {",
    "\t\t\t\tif (pra_touch_rd32(r, DW_IC_RAW_INTR_STAT) &",
    "\t\t\t\t    DW_IC_INTR_TX_ABRT) {",
    "\t\t\t\t\terror = ENXIO;",
    "\t\t\t\t\tbreak;",
    "\t\t\t\t}",
    "\t\t\t\tif (pra_touch_rd32(r, DW_IC_TXFLR) <",
    "\t\t\t\t    DW_IC_TXFLR_PUSH) {",
    "\t\t\t\t\troom = true;",
    "\t\t\t\t\tbreak;",
    "\t\t\t\t}",
    "\t\t\t}",
    "\t\t\tif (!room) {",
    "\t\t\t\tif (error == 0) {",
    "\t\t\t\t\terror = ETIMEDOUT;",
    "\t\t\t\t}",
    "\t\t\t\tbreak;",
    "\t\t\t}",
    "\t\t\tuint32_t cmd = DW_IC_CMD_READ;",
    "\t\t\tcmd_pushed++;",
    "\t\t\tif (cmd_pushed == rlen) {",
    "\t\t\t\tcmd |= DW_IC_CMD_STOP;",
    "\t\t\t}",
    "\t\t\tpra_touch_wr32(r, DW_IC_DATA_CMD, cmd);",
    "\t\t\tbool have = false;",
    "\t\t\tfor (unsigned i = 0; i < PRA_I2C_BYTE_POLLS && error == 0;",
    "\t\t\t\t    i++) {",
    "\t\t\t\tuint32_t raw = pra_touch_rd32(r,",
    "\t\t\t\t\t    DW_IC_RAW_INTR_STAT);",
    "\t\t\t\tif (raw & DW_IC_INTR_TX_ABRT) {",
    "\t\t\t\t\terror = ENXIO;",
    "\t\t\t\t\tbreak;",
    "\t\t\t\t}",
    "\t\t\t\tif ((raw & DW_IC_INTR_RX_FULL) ||",
    "\t\t\t\t\t    (pra_touch_rd32(r, DW_IC_STATUS) &",
    "\t\t\t\t\t    DW_IC_STATUS_RFNE)) {",
    "\t\t\t\t\thave = true;",
    "\t\t\t\t\tbreak;",
    "\t\t\t\t}",
    "\t\t\t}",
    "\t\t\tif (have) {",
    "\t\t\t\trd[got++] = (uint8_t)pra_touch_rd32(r,",
    "\t\t\t\t\t    DW_IC_DATA_CMD);",
    "\t\t\t} else if (error == 0) {",
    "\t\t\t\terror = ETIMEDOUT;",
    "\t\t\t}",
    "\t\t}",
    "\t}",
    "",
    "\twhile (error == 0 && got < rlen) {",
], "[2] the interleaved read phase")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0185 - the I2C read path: the interleaved push-and-drain (the
vendor's wire shape) - the descriptor read's first real test

work/rvr/ts/ + boot T8 (ring49): the bring-up replication WORKED -
the scan ACKed [1c] (the only device on the bus, 111 clean NACKs, 0
anomalies, 0 wedged), and BL_LAUNCH_APP was SENT (err=0, crc=0xc720)
- the first successful I2C transactions in the project's history.
The descriptor read then failed err=60 (ETIMEDOUT) with abrt=none,
flush=0 - the predicted CMD_READ latent bug: pra_i2c_xfer never
pushed read commands (the read loop only pops the RX FIFO), so no
data could ever clock in - a "read" was just the 2-byte
register-address write with an empty RX FIFO.

This patch (v2): (1) the write phase ALWAYS ends with STOP - the
read transaction starts fresh; (2) the INTERLEAVED read phase: per
byte - TXFLR-gated push of ONE CMD_READ (STOP on the last), a
bounded wait, a pop - any rlen works (the push-all form overflowed
the 64-entry RX FIFO above 64 bytes: the reports run up to 128).
The existing drain loop stays as the no-op safety net. The BL write
(rlen=0) is byte-identical; the scan is unaffected (its read
commands are pushed inline).

Neither multi-byte read form was ever proven on this hardware (the
read commands were never pushed at all before 0185) - this patch
tests the simpler separate-STOP form first; the falsifier ladder
covers both outcomes.

Decodes (the next pratouchreset=1 boot): the descriptor read
returns the REAL HID descriptor - len=32 bcd=0x100 = app mode
confirmed, pra_live=true, the reports flow (touch, at the 1 Hz
heartbeat pace until the IRQ rung); a DIFFERENT descriptor = the IC
is in a different mode than assumed (the desc length and rid name
it); err=60 again with the read commands pushed = the IC accepted
the write but never sent data (the read-side deeper rung); err=6
again = a regression against T8 - investigate as a
state-persistence question (the mux/pull-up/reset state lost).

Marker: no new print - the observable = the existing 'HID desc'
line's outcome (the CI assert covers the path).
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0185")
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
i_push = next(i for i, l in enumerate(pt) if "the read phase - push ONE read command" in l)
i_wloop = next(i for i, l in enumerate(pt) if "while (error == 0 && pushed < wlen)" in l)
i_drain = next(i for i, l in enumerate(pt) if "while (error == 0 && got < rlen)" in l)
assert i_wloop < i_push < i_drain, \
    f"the order: write loop @{i_wloop+1} < the push phase @{i_push+1} < the drain @{i_drain+1}"
print(f"[verify] write loop @{i_wloop+1} < push phase @{i_push+1} < drain @{i_drain+1}")
scan_text = "\n".join(pt)
assert "if (pushed == wlen) {" in scan_text and "if (rlen == 0 &&" not in scan_text, \
    "the STOP rides the last write byte unconditionally"
assert scan_text.count("pra_touch_wr32(r, DW_IC_DATA_CMD,") == 2, \
    "two DATA_CMD WRITE sites in pra_i2c_xfer (the write loop + the read push)"
depth = 0
for l in pt:
    for ch in l:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
assert depth == 0, f"the brace balance: {depth}"
print("[verify] braces balanced")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0185 applies to the reconstructed post-0184 base")

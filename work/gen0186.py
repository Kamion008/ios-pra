#!/usr/bin/env python3
"""gen0186.py - build xnu/patches/0186-pra-i2c-repeated-start.patch.

Base: the post-0185 pra_touch.c, reconstructed locally
(work/ci186/post0185 = the post-0184 reconstruction + the 0185 patch
applied; 0185 touches pra_touch.c only, verified during gen0185).

ROOT CAUSE (boot T9, ring50): the read path WORKS - 32 bytes
received (err=0), the interleaved push-and-drain executed flawlessly
- but the data = VARIED bytes, NOT the HID descriptor (len=0
bcd=0x76d2 rid=0x5ac7...; the parse gate rejected correctly). = the
predicted pointer-drop branch: the SEPARATE-STOP form (0185) makes
the IC drop its register pointer on the STOP - the fresh addr+R
read without the pointer returns the IC's default-read data (its
sensor state), not register 0x0001's descriptor. The base comment's
ORIGINAL design (the repeated-start read - the HID-over-I2C spec
form) is the alternative: the register pointer STAYS set across the
restart.

THIS PATCH: the REPEATED-START form.
1. The write phase does NOT stop (when rlen > 0): the last write
   byte goes out WITHOUT STOP, and the first CMD_READ triggers the
   REPEATED START at the wr->rd switch (RESTART_EN is already in
   CON=0x63). The register pointer stays set - the read returns
   register 0x0001's descriptor bytes.
2. The interleaved read phase stays unchanged (the restart happens
   at the first CMD_READ; the subsequent CMD_READs continue the
   same transaction; the last read carries STOP).
3. The write-only transactions (the BL frame, rlen=0) keep their
   STOP - unchanged.

The falsifier ladder (the next pratouchreset=1 boot): the descriptor
read returns len=32 bcd=0x100 = the app mode + the routing confirmed
- pra_live=true, the reports flow (touch!); the same varied garbage
= the pointer was NOT the (only) problem - the IC's MODE rung next
(the BL status read: is the IC in bootloader mode despite the ACKed
BL_LAUNCH?); a different fixed pattern = a different register space
(the pointer landed somewhere else).
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci186/post0185/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0186-pra-i2c-repeated-start.patch"
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

# [1] the write phase: the STOP reverts to write-only-only (the
# repeated-start form: no STOP before the reads)
pt, m = replace_block(pt, [
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
], [
    "\t\t\t/* 0186: the REPEATED-START form - when a read follows,",
    "\t\t\t * the write phase does NOT stop: the last write byte",
    "\t\t\t * goes out WITHOUT STOP and the first read command",
    "\t\t\t * triggers the REPEATED START at the wr->rd switch",
    "\t\t\t * (RESTART_EN is in CON=0x63). The register pointer",
    "\t\t\t * STAYS set across the restart - the read returns the",
    "\t\t\t * descriptor bytes (the separate-STOP form dropped the",
    "\t\t\t * pointer: boot T9's ring50, varied non-descriptor",
    "\t\t\t * bytes). The STOP still rides the last write byte for",
    "\t\t\t * WRITE-ONLY transactions (the BL frame). */",
    "\t\t\tif (rlen == 0 && pushed == wlen) {",
    "\t\t\t\tcmd |= DW_IC_CMD_STOP;",
    "\t\t\t}",
], "[1] the repeated-start STOP revert")
log.append(m)

# [2] the read-phase comment: the restart wording
pt, m = replace_block(pt, [
    "\t/* 0185: the read phase - push ONE read command, drain ONE",
    "\t * byte, repeat (the INTERLEAVED form): the write phase's STOP",
    "\t * terminates the write transaction and each CMD_READ runs a",
    "\t * fresh START+addr+R+byte+STOP. The 0172-0184 code never",
    "\t * pushed read commands - no data could ever clock in (the",
    "\t * err=60 signature, boot T8's desc read with abrt=none).",
    "\t * Interleaved, NOT push-all-then-drain: the RX FIFO is 64",
    "\t * entries and the report reads run up to 128 bytes - the",
    "\t * push-all form overflows above 64 (the round-1 K4 FAULT). */",
], [
    "\t/* 0186: the read phase - push ONE read command, drain ONE",
    "\t * byte, repeat (the INTERLEAVED form): the write phase's",
    "\t * last byte went out WITHOUT STOP, and the FIRST CMD_READ",
    "\t * triggers the REPEATED START at the wr->rd switch",
    "\t * (RESTART_EN) - the register pointer stays set, rlen bytes",
    "\t * clock in, the last carries STOP. The 0172-0184 code never",
    "\t * pushed read commands at all; 0185 tested the separate-STOP",
    "\t * form (the pointer dropped - ring50); 0186 tests the",
    "\t * repeated-start form (the HID spec). Interleaved, NOT",
    "\t * push-all-then-drain: the RX FIFO is 64 entries and the",
    "\t * report reads run up to 128 bytes (the round-1 K4 FAULT). */",
], "[2] the read-phase comment")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0186 - the REPEATED-START form: the write does not stop, the
register pointer survives the wr->rd switch

work/rvr/ts/ + boot T9 (ring50): the read path WORKS (32 bytes
received, err=0, the interleaved push-and-drain flawless) but the
data = VARIED bytes, NOT the HID descriptor (len=0 bcd=0x76d2
rid=0x5ac7...; the parse gate rejected correctly). = the predicted
pointer-drop branch: the SEPARATE-STOP form (0185) makes the IC drop
its register pointer on the STOP - the fresh addr+R read without the
pointer returns the IC's default-read data, not register 0x0001's
descriptor. The base comment's ORIGINAL design (the repeated-start
read - the HID-over-I2C spec form, RESTART_EN in CON) is the
alternative: the register pointer STAYS set across the restart.

This patch: the write phase does NOT stop when a read follows (the
last write byte goes out WITHOUT STOP; the first read command
triggers the repeated start at the wr->rd switch; RESTART_EN is
already in CON=0x63). The interleaved read phase stays. The
write-only transactions (the BL frame) keep their STOP.

Decodes (the next pratouchreset=1 boot): the descriptor read
returns len=32 bcd=0x100 = the app mode + the routing confirmed -
pra_live=true, the reports flow (touch!); the same varied garbage =
the pointer was not the (only) problem - the IC's MODE rung next
(the BL status read: the IC may still be in bootloader mode despite
the ACKed BL_LAUNCH frame); a different fixed pattern = the pointer
landed in a different register space (the address/rung question).

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
scratch = tempfile.mkdtemp(prefix="v0186")
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
scan_text = "\n".join(pt)
assert "if (rlen == 0 && pushed == wlen) {" in scan_text, "the STOP reverted to write-only-only"
assert scan_text.count("if (pushed == wlen) {") == 0 or \
    scan_text.count("if (pushed == wlen) {") == 0, "the 0185 whole-word STOP form removed"
assert "REPEATED START" in scan_text, "the restart wording present"
assert scan_text.count("pra_touch_wr32(r, DW_IC_DATA_CMD,") == 2, \
    "two DATA_CMD WRITE sites in pra_i2c_xfer (unchanged)"
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
print("[done] VERIFY PASS: 0186 applies to the reconstructed post-0185 base")

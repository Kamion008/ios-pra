#!/usr/bin/env python3
"""gen0181.py - build xnu/patches/0181-pra-i2c-abrt-diag.patch.

Base: the CI-compiled tree from run 44362560978
(work/ci181/post0180) - the post-0180 state for pra_touch.c, i.e. the
source of the kernel currently flashed (kernel 1efdf29d, boot T4).
NOTE: the task brief named run 44358321437 (post-0179) as the base, but
0180 modifies pra_touch.c itself (the rails block in the reset/launch
path, verified by diffing the two buildtrees), so the post-0180 tree is
the correct base: 0181's hunks must apply onto the stack AFTER 0180.

PURPOSE (work/i2c-research-2026-11-18.md, VERIFIED): the DW controller's
abort-reason register IC_TX_ABRT_SOURCE (0xFFD73000 + 0x80) names the
exact failure of every aborted transaction - bit 0 = 7-bit target
address NACK, bit 3 = data byte NACK, bit 12 = arbitration lost,
bit 11 = master disabled, bit 9 = the sticky restart-disabled abort,
bit 16 = software abort; bits [31:23] = TX_FLUSH_CNT, the count of
queued TX commands the abort destroyed (13 = the whole 13-byte BL
frame flushed at address time; smaller = the abort won mid-push -
race-dependent. The register preamble's "cleared on the CLR read
except Bit 9" covers the count field (per-transaction); the count
field's own description adds a clear-on-disable). Numeric
assignments cross-
verified against Linux v6.1 i2c-designware-core.h:145-158 AND the
Huawei i2c_designware-hs fork (i2c-designware-core.c:134-146) that runs
on THIS silicon; COMP_VERSION 3132302a = "120*" = DW v1.20*.

THE CAPTURE ORDER IS THE POINT: pra_i2c_xfer's exit reads CLR_TX_ABRT
(read-to-clear), and reading it WIPES TX_ABRT_SOURCE ("...cleared
whenever the IC_CLR_TX_ABRT is read. Preserve it beforehand",
i2c-designware-master.c:687-694; the fork duplicates the comment at
core.c:1005-1011). A diagnostic at the failure print sites would always
read 0. So the snapshot moves INSIDE the xfer exit, before the clear;
the reset/launch failure sites print it via pra_i2c_diag.

Reads and static stores only - no controller writes, no retries.
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci181/post0180/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0181-pra-i2c-abrt-diag.patch"
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

def insert_before(lines, anchor, new, tag):
    i = anchor_unique(lines, anchor, tag)
    return lines[:i] + new + lines[i:], f"{tag}: inserted before line {i+1}"

pt = read(f"{BASE}/{TARGET}")
log = []

# [1] the missing abort-source register define, numeric order in the
# block (0x74 TXFLR < 0x80 TX_ABRT_SOURCE < 0x9C ENABLE_STATUS)
pt, m = insert_before(pt, [
    "#define DW_IC_ENABLE_STATUS     0x9Cu",
], [
    "#define DW_IC_TX_ABRT_SOURCE    0x80u   /* abort reason bits; wiped",
    "\t * by the CLR_TX_ABRT (0x54) read-to-clear */",
], "[1] DW_IC_TX_ABRT_SOURCE define")
log.append(m)

# [2] the abort-source bit decode (numbers VERIFIED: Linux v6.1
# core.h:145-158 + the Huawei fork core.c:134-146 on this silicon;
# USER_ABRT bit 16 + TX_FLUSH_CNT [31:23] per the RP2040 register ref)
pt, m = insert_before(pt, [
    "#define DW_IC_STATUS_BUSY       0x21u   /* ACTIVITY | MASTER_ACTIVITY */",
], [
    "/* 0181: IC_TX_ABRT_SOURCE decode - the numeric bit assignments",
    " * VERIFIED against Linux v6.1 i2c-designware-core.h:145-158 AND the",
    " * Huawei i2c_designware-hs fork (i2c-designware-core.c:134-146, the",
    " * driver that runs on this silicon); USER_ABRT bit 16 + the",
    " * TX_FLUSH_CNT field [31:23] per the RP2040 DW register reference.",
    " * Slave-side bits (13-15) cannot fire with CON SLAVE_DIS set. */",
    "#define DW_IC_ABRT_7B_ADDR_NOACK    (1u << 0)   /* target addr NACK */",
    "#define DW_IC_ABRT_TXDATA_NOACK     (1u << 3)   /* data byte NACK */",
    "#define DW_IC_ABRT_SBYTE_NORSTRT    (1u << 9)   /* restart disabled",
    "\t * (sticky: survives CLR_TX_ABRT until the source is fixed) */",
    "#define DW_IC_ABRT_MASTER_DIS       (1u << 11)  /* master disabled */",
    "#define DW_IC_ABRT_ARB_LOST         (1u << 12)  /* lost arbitration */",
    "#define DW_IC_ABRT_USER_ABRT        (1u << 16)  /* software abort via",
    "\t * the ENABLE ABORT bit */",
    "#define DW_IC_ABRT_FLUSH_CNT        0xff800000u /* [31:23] = the TX",
    "\t * commands the abort destroyed; the register preamble's",
    "\t * \"cleared on the CLR read except Bit 9\" makes it per-txn;",
    "\t * the field doc adds a clear-on-disable */",
], "[2] the ABRT bit decode defines")
log.append(m)

# [3] the exit-snapshot statics, file scope next to the other I2C state
# (pra_tar) - declared BEFORE pra_i2c_xfer (the use-before-decl guard
# below verifies it)
pt, m = insert_before(pt, [
    "static bool pra_live;                   /* descriptor parsed, reads allowed */",
], [
    "/* 0181: the transaction-exit state, captured INSIDE pra_i2c_xfer",
    " * before its read-to-clear (reading CLR_TX_ABRT wipes the volatile",
    " * TX_ABRT_SOURCE bits; a call-site read would keep only the sticky",
    " * bit 9). Written on every exit by the probe AND the worker; read",
    " * only by the probe's pra_i2c_diag, before the worker starts. No",
    " * MMIO writes anywhere - reads and static stores only. */",
    "static uint32_t pra_i2c_last_abrt;      /* IC_TX_ABRT_SOURCE at exit */",
    "static uint32_t pra_i2c_last_tar;       /* IC_TAR at exit */",
    "static uint32_t pra_i2c_last_con;       /* IC_CON at exit */",
    "static uint32_t pra_i2c_last_en;        /* IC_ENABLE at exit */",
    "static uint32_t pra_i2c_last_enstat;    /* IC_ENABLE_STATUS at exit */",
    "static uint32_t pra_i2c_last_stat;      /* IC_STATUS at exit */",
    "",
], "[3] the exit-snapshot statics")
log.append(m)

# [4] the capture, inside pra_i2c_xfer BEFORE the final read-to-clear
# (the same two clear lines appear at the xfer entry, so the anchor
# carries the following ETIMEDOUT line for uniqueness)
pt, m = insert_before(pt, [
    "\t(void)pra_touch_rd32(r, DW_IC_CLR_TX_ABRT);",
    "\t(void)pra_touch_rd32(r, DW_IC_CLR_STOP_DET);",
    "\tif (error == ETIMEDOUT) {",
], [
    "\t/* 0181: snapshot the exit state BEFORE the read-to-clears below -",
    "\t * reading CLR_TX_ABRT wipes TX_ABRT_SOURCE (the abort reason),",
    "\t * so a call-site diagnostic would always read 0. */",
    "\tpra_i2c_last_abrt = pra_touch_rd32(r, DW_IC_TX_ABRT_SOURCE);",
    "\tpra_i2c_last_tar = pra_touch_rd32(r, DW_IC_TAR);",
    "\tpra_i2c_last_con = pra_touch_rd32(r, DW_IC_CON);",
    "\tpra_i2c_last_en = pra_touch_rd32(r, DW_IC_ENABLE);",
    "\tpra_i2c_last_enstat = pra_touch_rd32(r, DW_IC_ENABLE_STATUS);",
    "\tpra_i2c_last_stat = pra_touch_rd32(r, DW_IC_STATUS);",
], "[4] the exit capture in pra_i2c_xfer")
log.append(m)

# [5] the snapshot invalidation at transaction entry (pra_touch_txn,
# bus_on path): a failed setup would otherwise leave the PREVIOUS
# transaction's abort state in the statics and mislabel this attempt
pt, m = replace_block(pt, [
    "\treowned = pra_i2c_bus_take(PRA_BUS_TOUCH);",
    "\tif (reowned) {",
    "\t\tpra_tar = 0;",
    "\t}",
], [
    "\treowned = pra_i2c_bus_take(PRA_BUS_TOUCH);",
    "\tif (reowned) {",
    "\t\tpra_tar = 0;",
    "\t}",
    "\t/* 0181: invalidate the exit snapshot for this attempt - a failed",
    "\t * setup (below) would otherwise report the previous",
    "\t * transaction's abort state. The xfer exit re-captures. */",
    "\tpra_i2c_last_abrt = 0;",
    "\tpra_i2c_last_tar = 0;",
    "\tpra_i2c_last_con = 0;",
    "\tpra_i2c_last_en = 0;",
    "\tpra_i2c_last_enstat = 0;",
    "\tpra_i2c_last_stat = 0;",
], "[5] the snapshot invalidation in pra_touch_txn")
log.append(m)

# [6] the diag helper, before its first call site (pra_touch_reset_launch)
pt, m = insert_before(pt, [
    "/*",
    " * 0177 rung A (pratouchreset=1, OFF by default): readback-verified XRES",
], [
    "/*",
    " * 0181: decode the captured transaction-exit state after a FAILED",
    " * transaction in the reset/launch path. The abort-source bit numbers",
    " * are VERIFIED (Linux v6.1 i2c-designware-core.h:145-158 + the Huawei",
    " * fork core.c:134-146 on this silicon): bit 0 = the 7-bit TARGET",
    " * ADDRESS was NACKed (no chip at TAR, or a silent/dead IC), bit 3 =",
    " * a data byte was NACKed (IC alive, rejecting payload), bit 12 =",
    " * arbitration lost (something holds the bus), bit 11 = master",
    " * disabled (config lost), bit 9 = the sticky restart-disabled abort,",
    " * bit 16 = software abort. The high field [31:23] = TX_FLUSH_CNT,",
    " * the count of queued TX commands the abort destroyed: for the",
    " * 13-byte BL frame 13 = flushed at address time; smaller = the",
    " * abort won mid-push (race-dependent vs the push loop). The",
    " * register preamble's \"cleared whenever the IC_CLR_TX_ABRT is",
    " * read - Except for Bit 9\" covers the count field (per-txn);",
    " * the count field's own description adds \"cleared whenever I2C",
    " * is disabled\" (RP2040 i2c.h:1908-1910 vs :1929-1931, quoted in",
    " * work/evidence-abrt-sources.md). tar/con print the FULL registers",
    " * so the verify sees TAR[12] (10-bit mode) and CON[15:8] too.",
    " * tar/con are the ENGINE's",
    " * actual config against what pra_i2c_setup wrote (0x1c/0x63): a",
    " * mismatch means the config never took. ver/type re-read live:",
    " * 3132302a/44570140 = the controller window still answers (a",
    " * clock-gated host reads as an external abort, not data; the",
    " * IOMCU-reset read behavior itself is UNKNOWN).",
    " */",
    "static void",
    "pra_i2c_diag(const char *what, int error)",
    "{",
    "\tuint32_t abrt = pra_i2c_last_abrt;",
    "\tuint32_t ver = pra_touch_rd32(pra_i2c_regs, DW_IC_COMP_VERSION);",
    "\tuint32_t type = pra_touch_rd32(pra_i2c_regs, DW_IC_COMP_TYPE);",
    "",
    "\tprintf(\"PRA i2c: %s err=%d abrt=%08x tar=%08x/%02x con=%08x \"",
    "\t    \"en=%02x enstat=%02x stat=%02x flush=%u ver=%08x type=%08x\",",
    "\t    what, error, abrt, pra_i2c_last_tar,",
    "\t    PRA_TOUCH_ADDR & 0x7fu, pra_i2c_last_con,",
    "\t    pra_i2c_last_en & 0xffu, pra_i2c_last_enstat & 0xffu,",
    "\t    pra_i2c_last_stat & 0xffu,",
    "\t    (abrt & DW_IC_ABRT_FLUSH_CNT) >> 23, ver, type);",
    "\tif (abrt == 0) {",
    "\t\tprintf(\" abrt=none\\n\");",
    "\t\treturn;",
    "\t}",
    "\tif (abrt & DW_IC_ABRT_7B_ADDR_NOACK) {",
    "\t\tprintf(\" ADDR7_NACK\");",
    "\t}",
    "\tif (abrt & DW_IC_ABRT_TXDATA_NOACK) {",
    "\t\tprintf(\" DATA_NACK\");",
    "\t}",
    "\tif (abrt & DW_IC_ABRT_ARB_LOST) {",
    "\t\tprintf(\" ARB_LOST\");",
    "\t}",
    "\tif (abrt & DW_IC_ABRT_MASTER_DIS) {",
    "\t\tprintf(\" MASTER_DIS\");",
    "\t}",
    "\tif (abrt & DW_IC_ABRT_SBYTE_NORSTRT) {",
    "\t\tprintf(\" SBYTE_NORSTRT\");",
    "\t}",
    "\tif (abrt & DW_IC_ABRT_USER_ABRT) {",
    "\t\tprintf(\" USER_ABRT\");",
    "\t}",
    "\tprintf(\"\\n\");",
    "}",
    "",
], "[6] the pra_i2c_diag helper")
log.append(m)

# [7] the BL_LAUNCH failure site: print the snapshot (this site only
# runs behind pratouchreset=1 - no gate needed)
pt, m = replace_block(pt, [
    "\t\tprintf(\"PRA touch: BL_LAUNCH_APP write failed err=%d, probe \"",
    "\t\t    \"continues\\n\", error);",
], [
    "\t\tprintf(\"PRA touch: BL_LAUNCH_APP write failed err=%d, probe \"",
    "\t\t    \"continues\\n\", error);",
    "\t\tpra_i2c_diag(\"bl_launch\", error);",
], "[7] the BL_LAUNCH failure diag")
log.append(m)

# [8] the descriptor-read failure site: the same print + the snapshot.
# Gated on pra_touch_bus_on: without pratouchreset=1 NO transaction ever
# runs (pra_i2c_xfer returns ENXIO at its entry check) and the diag
# would print inert zeros on every standard boot.
pt, m = replace_block(pt, [
    "\t\tprintf(\"PRA touch: HID desc read failed err=%d \"",
    "\t\t    \"(%s); irq polling continues\\n\", error,",
    "\t\t    error == ENXIO ? \"address NACK\" : \"bus timeout\");",
], [
    "\t\tprintf(\"PRA touch: HID desc read failed err=%d \"",
    "\t\t    \"(%s); irq polling continues\\n\", error,",
    "\t\t    error == ENXIO ? \"address NACK\" : \"bus timeout\");",
    "\t\tif (pra_touch_bus_on) {",
    "\t\t\tpra_i2c_diag(\"hid_desc\", error);",
    "\t\t}",
], "[8] the descriptor failure diag (bus_on-gated)")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0181 - the I2C abort-source diagnostic (ABRT_SOURCE + the TAR/CON verify)

work/i2c-research-2026-11-18.md (VERIFIED): the DW controller's
abort-reason register IC_TX_ABRT_SOURCE (0xFFD73000 + 0x80) names the
exact failure of every aborted transaction - bit 0 = the 7-bit target
address was NACKed, bit 3 = a data byte NACKed, bit 12 = arbitration
lost, bit 11 = master disabled, bit 9 = the sticky restart-disabled
abort, bit 16 = software abort; bits [31:23] = TX_FLUSH_CNT, the count
of queued TX commands the abort destroyed (13 = the whole 13-byte BL
frame flushed at address time; smaller = the abort won mid-push - the
count is race-dependent vs the push loop; the register preamble's
"cleared on the CLR read except Bit 9" makes it per-transaction, and
the field doc adds a clear-on-disable). The numeric assignments are
cross-verified
against Linux v6.1 i2c-designware-core.h:145-158 and the Huawei
i2c_designware-hs fork (i2c-designware-core.c:134-146) that runs on
this silicon; COMP_VERSION 3132302a = "120*" = DW v1.20*.

THE CAPTURE ORDER IS THE POINT: pra_i2c_xfer's exit reads CLR_TX_ABRT
(read-to-clear), and reading it WIPES TX_ABRT_SOURCE ("...cleared
whenever the IC_CLR_TX_ABRT is read. Preserve it beforehand",
i2c-designware-master.c:687-694; the fork duplicates the comment at
core.c:1005-1011). So the snapshot is taken INSIDE the xfer exit,
before that clear; the reset/launch failure sites (the BL_LAUNCH_APP
write, the descriptor read) print it through pra_i2c_diag. The
descriptor site is gated on pra_touch_bus_on (without pratouchreset=1
no transaction ever runs - the print would be inert noise on every
standard boot).

This patch adds no CONTROLLER writes and no retries. The new reads
(TAR/CON/ENABLE/ABRT_SOURCE + the live ver/type) sit in the same
mapped 4 KiB window
the transaction path actively uses, but they ARE new fault sites in
the narrow sense: a window dying between the xfer's last read and the
capture would fault on them where the old code would have continued.
Accepted, not engineered around - the diag runs at most twice per
boot against a window that answered MMIO microseconds earlier, and
hiding the reads would defeat the diagnostic. The transaction
sequence stays byte-for-byte comparable and the boot adds one decode
line per failed transaction.

Decodes (the next pratouchreset=1 boot; NOTE the raw abrt word carries
the TX_FLUSH_CNT field in [31:23]: flush=13 shifts to 0x06800000, so a
bit-0 abort with 13 commands flushed reads 06800001, not 00000001 -
read the low 17 bits as the cause and [31:23] as the count):
abrt=06800001 flush=13 tar=0000001c/1c ver=3132302a = "the IC at 0x1C
NACKed its address on a live controller with the config intact"
(IC-side: mode/timing/the address itself). flush = the queued TX
commands the abort destroyed - race-dependent vs the push loop; the
preamble's except-Bit-9 rule makes it per-transaction.
abrt=00001000 = arbitration lost (bus clamp); abrt=00000008 = data
NACK (IC alive, rejecting the payload); abrt=00000000 = no abort
fired (bus hang or no STOP, or the setup never ran - tar=00/1c
discriminates). The fix follows from the line.

Marker asserted in CI (direct yml commit): 'PRA i2c: '.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0181")
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

# use-before-declaration guard (run #66 lesson): every new file-scope
# symbol must be declared before its first non-comment use. Word-
# boundary matching: "pra_i2c_last_en" must not match inside
# "pra_i2c_last_enstat" (the substring form mis-locates first use).
import re as _re
NEW_SYMS = ("pra_i2c_last_abrt", "pra_i2c_last_tar", "pra_i2c_last_con",
            "pra_i2c_last_en", "pra_i2c_last_enstat", "pra_i2c_last_stat",
            "pra_i2c_diag")
for sym in NEW_SYMS:
    pat = _re.compile(rf"\b{sym}\b")
    decl = next(i for i, l in enumerate(pt) if pat.search(l)
                and (l.startswith("static ") or l.startswith("pra_i2c_diag(")))
    first_use = next(i for i, l in enumerate(pt)
                     if pat.search(l) and i != decl
                     and not l.lstrip().startswith(("//", "/*", "*")))
    assert first_use > decl, \
        f"{sym}: use at {first_use+1} [{pt[first_use][1:60]}] precedes decl at {decl+1} [{pt[decl][1:60]}]"
    print(f"[verify] {sym}: decl {decl+1} < first use {first_use+1}")

# structural assertions: the capture precedes the clear that wipes it;
# the diag precedes both call sites; the marker string is present
i_cap = next(i for i, l in enumerate(pt) if "pra_i2c_last_abrt = pra_touch_rd32" in l)
i_clr = next(i for i, l in enumerate(pt)
             if "DW_IC_CLR_TX_ABRT" in l and i > i_cap and "(void)" in l)
assert i_cap < i_clr, f"capture @{i_cap+1} must precede the exit clear @{i_clr+1}"
print(f"[verify] capture @{i_cap+1} precedes the exit CLR_TX_ABRT read @{i_clr+1}")
i_diag = next(i for i, l in enumerate(pt) if l.startswith("pra_i2c_diag("))
i_bl = next(i for i, l in enumerate(pt) if 'pra_i2c_diag("bl_launch"' in l)
i_desc = next(i for i, l in enumerate(pt) if 'pra_i2c_diag("hid_desc"' in l)
assert i_diag < i_bl < i_desc, "the helper must precede both call sites"
print(f"[verify] diag @{i_diag+1} < bl site @{i_bl+1} < desc site @{i_desc+1}")
assert sum(1 for l in pt if "PRA i2c: " in l) == 1, "the marker string must appear exactly once"
assert "(1u << 9)" in "\n".join(pt) and "(1u << 12)" in "\n".join(pt), "the verified bit numbers"
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0181 applies to the post-0180 CI base (run 44362560978)")

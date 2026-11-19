#!/usr/bin/env python3
"""gen0183.py - build xnu/patches/0183-pra-i2c-bus-scan.patch.

Base: the post-0182 pra_touch.c, reconstructed locally
(work/ci183/post0182 = work/ci182/post0181 + the 0182 patch applied;
0182 touches pra_touch.c only, and its clean application to this
exact base was verified during gen0182). The CI buildtree download
for run 44565761460 failed twice on network timeouts - the
reconstruction is deterministic.

ROOT CAUSE (boot T6, ring47): the 0182 pad-mux fix CONFIRMED the
hypothesis as a real defect - the pads sat in the idle function (0x0)
since 0172 and were moved to I2C (0x1, readback OK) - AND the ladder
STILL NACKs (ADDR7_NACK x2, tar=1c/1c verified, COMP live). The
remaining fork: the bus electrically dead (the cfg words = 0, no
pull config; the board's external pull-ups unverified) vs a deaf IC
at 0x1c. A single-address probe cannot tell them apart.

THIS PATCH (v3 - the round-1 K4 refutation fixed: the scan
establishes its OWN controller config via pra_i2c_setup, else the
bootloader's leftover CON/HCNT/LCNT decide whether DATA_CMD starts a
transfer at all; the round-1 K3 category error fixed: the scan
writes SHARED-controller state and takes the bus mutex; the round-2
K4/K5 refutations fixed: the abort reason is captured BEFORE the
read-to-clear wipes it - a controller-side abort prints identical to
a clean address NACK otherwise - and the wedged case is COUNTERED
instead of silently scored as no-ACK): the I2C bus scan - addresses
0x08-0x77 (0x77-0x08+1 = 112, script-quoted in
work/evidence-padmux-arithmetic.md), ONE one-byte READ command each
(START+addr+R+STOP: nothing is written to any device). Any ACK = the
bus is electrically alive and 0x1c specifically is the problem; zero
ACK with every NACK clean (bit 0 only) = the bus itself is dead; any
other abort pattern = the controller is misbehaving (named in the
print). The scan runs AFTER the gpio reset (the IC in its freshest
bootloader-mode state) and BEFORE the BL_LAUNCH frame. The ACK list
prints in ONE snprintf-assembled line. Leaves TAR changed: pra_tar =
0 forces the ladder's re-setup to 0x1c. Runtime bounded: 112
addresses x 3 bounded polls. The bus mutex IS taken (the charger
co-owner's register state is the boot default, but the charger
driver never runs - zero PRA-charger lines in every ring; the lock
is held ~1s worst case, no sleeps inside).
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci183/post0182/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0183-pra-i2c-bus-scan.patch"
TARGET = "bsd/dev/pra_touch.c"

def read(path):
    return open(path, encoding="utf-8").read().splitlines()

def anchor_unique(lines, anchor, tag):
    n = sum(1 for i in range(len(lines))
            if tuple(lines[i:i+len(anchor)]) == tuple(anchor))
    assert n == 1, f"{tag}: anchor not unique ({n} hits): {anchor[0][:60]!r}"
    return next(i for i in range(len(lines))
                if tuple(lines[i:i+len(anchor)]) == tuple(anchor))

def insert_before(lines, anchor, new, tag):
    i = anchor_unique(lines, anchor, tag)
    return lines[:i] + new + lines[i:], f"{tag}: inserted before line {i+1}"

pt = read(f"{BASE}/{TARGET}")
log = []

SCAN = [
    "\t/* 0183: the I2C bus scan (see the patch header). ONE one-byte",
    "\t * READ command per address - START+addr+R+STOP, nothing is",
    "\t * written to any device. The classified print: the dead-bus",
    "\t * verdict is only derivable when EVERY non-ACK was a clean",
    "\t * bit-0 NACK and nothing wedged. The scan establishes its own",
    "\t * config (pra_i2c_setup - the sole CON/HCNT/LCNT writer) and",
    "\t * takes the bus mutex (SHARED-controller state). Leaves TAR",
    "\t * changed: pra_tar = 0 forces the ladder's re-setup to 0x1c. */",
    "\t{",
    "\t\tuint8_t acks[112];",
    "\t\tchar list[(112 * 3) + 8];",
    "\t\tunsigned ackn = 0, addr, i, off;",
    "\t\tunsigned clean_nack = 0, anomalies = 0, wedged = 0;",
    "\t\tuint32_t an_abrt = 0;",
    "\t\tuint8_t an_addr = 0;",
    "\t\tint n;",
    "\t\tbool scanned = false;",
    "",
    "\t\tlist[0] = '\\0';",
    "\t\toff = 0;",
    "\t\tpra_i2c_bus_take(PRA_BUS_TOUCH);",
    "\t\tif (pra_i2c_setup() == 0) {",
    "\t\t\tscanned = true;",
    "\t\t\tfor (addr = 0x08u; addr <= 0x77u; addr++) {",
    "\t\t\t\tuint32_t raw, abrt;",
    "\t\t\t\tbool nack = true;",
    "",
    "\t\t\t\tpra_touch_wr32(pra_i2c_regs, DW_IC_ENABLE, 0);",
    "\t\t\t\tif (pra_i2c_wait_enable(false)) {",
    "\t\t\t\t\twedged++;   /* the controller never disabled */",
    "\t\t\t\t\tcontinue;",
    "\t\t\t\t}",
    "\t\t\t\t(void)pra_touch_rd32(pra_i2c_regs,",
    "\t\t\t\t\t    DW_IC_CLR_TX_ABRT);",
    "\t\t\t\t(void)pra_touch_rd32(pra_i2c_regs,",
    "\t\t\t\t\t    DW_IC_CLR_STOP_DET);",
    "\t\t\t\tpra_touch_wr32(pra_i2c_regs, DW_IC_TAR,",
    "\t\t\t\t\t    addr & 0x7fu);",
    "\t\t\t\t__asm__ volatile(\"dsb sy\" : : : \"memory\");",
    "\t\t\t\tpra_touch_wr32(pra_i2c_regs, DW_IC_ENABLE, 1);",
    "\t\t\t\tif (pra_i2c_wait_enable(true)) {",
    "\t\t\t\t\twedged++;   /* the controller never enabled */",
    "\t\t\t\t\tcontinue;",
    "\t\t\t\t}",
    "\t\t\t\tpra_touch_wr32(pra_i2c_regs, DW_IC_DATA_CMD,",
    "\t\t\t\t\t    DW_IC_CMD_READ | DW_IC_CMD_STOP);",
    "\t\t\t\tfor (i = 0; i < PRA_I2C_POLLS; i++) {",
    "\t\t\t\t\traw = pra_touch_rd32(pra_i2c_regs,",
    "\t\t\t\t\t\t    DW_IC_RAW_INTR_STAT);",
    "\t\t\t\t\tif (raw & DW_IC_INTR_TX_ABRT) {",
    "\t\t\t\t\t\tbreak;      /* abort */",
    "\t\t\t\t\t}",
    "\t\t\t\t\tif (raw & DW_IC_INTR_STOP_DET) {",
    "\t\t\t\t\t\tnack = false;   /* ACK */",
    "\t\t\t\t\t\tbreak;",
    "\t\t\t\t\t}",
    "\t\t\t\t}",
    "\t\t\t\tif (nack) {",
    "\t\t\t\t\t/* 0181's own lesson: reading CLR_TX_ABRT DESTROYS",
    "\t\t\t\t\t * TX_ABRT_SOURCE - capture the reason FIRST, else a",
    "\t\t\t\t\t * controller-side abort prints identical to a clean",
    "\t\t\t\t\t * address NACK and the dead-bus verdict is not",
    "\t\t\t\t\t * derivable (the round-2 K4 refutation fixed). */",
    "\t\t\t\t\tabrt = pra_touch_rd32(pra_i2c_regs,",
    "\t\t\t\t\t\t    DW_IC_TX_ABRT_SOURCE);",
    "\t\t\t\t\t/* the [31:23] TX_FLUSH_CNT rides in the same word on",
    "\t\t\t\t\t * EVERY abort (the ladder's own words: flush 24/2) -",
    "\t\t\t\t\t * the predicate MASKS it, else the clean-NACK branch",
    "\t\t\t\t\t * is unreachable (the round-3 K4 refutation fixed) */",
    "\t\t\t\t\tif ((abrt & ~DW_IC_ABRT_FLUSH_CNT) ==",
    "\t\t\t\t\t\t    DW_IC_ABRT_7B_ADDR_NOACK) {",
    "\t\t\t\t\t\tclean_nack++;",
    "\t\t\t\t\t} else if (anomalies == 0) {",
    "\t\t\t\t\t\tanomalies++;",
    "\t\t\t\t\t\tan_abrt = abrt;",
    "\t\t\t\t\t\tan_addr = (uint8_t)addr;",
    "\t\t\t\t\t}",
    "\t\t\t\t\t(void)pra_touch_rd32(pra_i2c_regs,",
    "\t\t\t\t\t\t    DW_IC_CLR_TX_ABRT);",
    "\t\t\t\t} else {",
    "\t\t\t\t\t(void)pra_touch_rd32(pra_i2c_regs,",
    "\t\t\t\t\t\t    DW_IC_DATA_CMD);   /* drain the byte */",
    "\t\t\t\t\t(void)pra_touch_rd32(pra_i2c_regs,",
    "\t\t\t\t\t\t    DW_IC_CLR_STOP_DET);",
    "\t\t\t\t\tif (ackn < sizeof(acks)) {",
    "\t\t\t\t\t\tacks[ackn++] = (uint8_t)addr;",
    "\t\t\t\t\t}",
    "\t\t\t\t}",
    "\t\t\t}",
    "\t\t} else {",
    "\t\t\tprintf(\"PRA i2c scan: skipped, setup failed\\n\");",
    "\t\t}",
    "\t\tpra_i2c_bus_drop();",
    "\t\tif (scanned) {",
    "\t\t\tfor (i = 0; i < ackn; i++) {",
    "\t\t\t\tn = snprintf(list + off, sizeof(list) - off,",
    "\t\t\t\t    \"%s%02x\", i ? \" \" : \"\", acks[i]);",
    "\t\t\t\tif (n < 0 || (unsigned)n >= sizeof(list) - off) {",
    "\t\t\t\t\tbreak;      /* the list truncated */",
    "\t\t\t\t}",
    "\t\t\t\toff += (unsigned)n;",
    "\t\t\t}",
    "\t\t\tprintf(\"PRA i2c scan: %u ACK, %u clean NACK, %u \",",
    "\t\t\t\t\"anomalies, %u wedged of 112: [%s]\\n\", ackn,",
    "\t\t\t\tclean_nack, anomalies, wedged, list);",
    "\t\t\tif (anomalies) {",
    "\t\t\t\tprintf(\"PRA i2c scan: anomaly abrt=%08x at %02x\\n\",",
    "\t\t\t\t\t    an_abrt, an_addr);",
    "\t\t\t}",
    "\t\t}",
    "\t\tpra_tar = 0;    /* the ladder's txn re-setups to 0x1c */",
    "\t}",
]

pt, m = insert_before(pt, [
    "\t/* 2. BL_LAUNCH_APP, byte-for-byte mainline cyttsp5.c:615-623. */",
], SCAN, "[1] the bus-scan block")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0183 - the I2C bus scan: probe 0x08-0x77 with one-byte reads -
the classified bus-dead vs deaf-IC discriminator

work/evidence-padmux-arithmetic.md + boot T6 (ring47): the 0182
pad-mux fix CONFIRMED a real defect - the SDA/SCL pads sat in the
idle function (0x0) since 0172, and the fix moved them to I2C (0x1,
readback sda=00000001 scl=00000001) - AND the ladder STILL NACKs
(ADDR7_NACK x2, tar=1c/1c verified in-engine, COMP live, identical
to T5). The routing was necessary but not sufficient. The remaining
fork, indistinguishable by a single-address probe: the bus
electrically dead (the cfg words = 0, no pull config; the board's
external pull-ups unverified) vs a deaf IC at 0x1c.

This patch (v3): the I2C bus scan. Addresses 0x08-0x77 (0x77-0x08+1
= 112, computed in work/evidence-padmux-arithmetic.md), ONE one-byte
READ command each (START+addr+R+STOP: nothing is written to any
device - the probe cannot disturb a live device). The scan
ESTABLISHES ITS OWN CONFIG (pra_i2c_setup once, before the loop -
the sole CON/HCNT/LCNT writer; probing on the bootloader's leftovers
could make DATA_CMD start no transfer at all), takes the bus mutex
(the scan writes SHARED-controller state), and classifies every
non-ACK: the abort reason is captured from TX_ABRT_SOURCE BEFORE the
read-to-clear wipes it (the 0181 lesson) - a clean bit-0 NACK counts
as no-device, any other abort pattern is an ANOMALY (master-disabled,
arb-lost, ...) printed with its address, and the wedged case (the
enable never followed) has its own counter instead of silently
scoring as no-ACK. The classified print:
'PRA i2c scan: <ACK> ACK, <n> clean NACK, <m> anomalies, <w> wedged
of 112: [list]' - the dead-bus verdict is only derivable when m = 0
and w = 0.

Decodes (the next pratouchreset=1 boot): '0 ACK, 112 clean NACK, 0
anomalies, 0 wedged' = the bus is electrically dead (the pull-up
question first); the ACK list contains 1c = the IC answers its
address (the bus alive, the IC alive - the ladder's next steps
become real); ACKs but not 1c = the bus is alive and the touch IC is
dead or mis-addressed (the power/mode rung); anomalies > 0 = the
controller is misbehaving (the named abort word + address); wedged >
0 = the controller stopped responding DURING the scan (the 0181
prints bracket it). The scan runs after the gpio reset (the IC in
its freshest bootloader-mode state - mainline cyttsp5 powers on in
bootloader mode and ACKs there) and before the BL_LAUNCH frame.

Marker asserted in CI (direct yml commit): 'PRA i2c scan:'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0183")
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
i_scan = next(i for i, l in enumerate(pt) if "0183: the I2C bus scan" in l)
i_done = next(i for i, l in enumerate(pt) if "reset gpio18.1 done" in l)
i_bl = next(i for i, l in enumerate(pt) if "2. BL_LAUNCH_APP" in l)
assert i_done < i_scan < i_bl, \
    f"the scan @{i_scan+1} must sit between the reset-done @{i_done+1} and the BL frame @{i_bl+1}"
print(f"[verify] reset-done @{i_done+1} < scan @{i_scan+1} < BL frame @{i_bl+1}")
scan_text = "\n".join(pt[i_done:i_bl])
assert scan_text.count("PRA i2c scan:") == 3, "three marker sites (skipped + result + anomaly)"
assert "pra_i2c_bus_take(PRA_BUS_TOUCH);" in scan_text, "the scan takes the bus mutex"
assert "pra_i2c_bus_drop();" in scan_text, "the scan drops it"
assert "if (pra_i2c_setup() == 0) {" in scan_text, "the known-config setup"
assert scan_text.count("pra_touch_wr32(pra_i2c_regs, DW_IC_DATA_CMD,") == 1, \
    "exactly one DATA_CMD write site in the scan"
assert "DW_IC_CMD_READ | DW_IC_CMD_STOP" in scan_text, "the probe is a READ command"
i_abrt = next(i for i, l in enumerate(pt[i_done:i_bl])
              if "DW_IC_TX_ABRT_SOURCE" in l)
i_clr = next(i for i, l in enumerate(pt[i_done:i_bl])
             if "DW_IC_CLR_TX_ABRT" in l and i > i_abrt)
assert i_abrt < i_clr, "the abort source is captured BEFORE its wipe"
print("[verify] the scan captures TX_ABRT_SOURCE before the CLR wipe")
assert "pra_tar = 0;" in scan_text, "the TAR re-setup sentinel"
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0183 applies to the reconstructed post-0182 base")

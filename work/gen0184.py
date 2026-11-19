#!/usr/bin/env python3
"""gen0184.py - build xnu/patches/0184-pra-bringup-replication.patch.

Base: the post-0183 pra_touch.c, reconstructed locally
(work/ci184/post0183 = the post-0182 reconstruction + the 0183 patch
applied; 0183 touches pra_touch.c only, verified during gen0183).
The CI buildtree download for run 44591973068: not fetched (the
network to the artifact blob timed out repeatedly this session) -
the reconstruction is deterministic.

ROOT CAUSE (work/driver-bringup-research-2026-11-19.md + boot T7's
scan: 0 ACK, 112 clean NACK = the bus electrically dead): the
reverse-engineered stock bring-up (the vendor cyttsp5 stack fetched
to work/rvr/) differs from our ladder in THREE verified deltas:

1. THE RESET POLARITY (the top candidate): the vendor drives gpio145
   IDLE HIGH and pulses LOW 40 ms (cyttsp5_platform.c:236-249 xres:
   HIGH 20 ms -> LOW 40 ms -> HIGH 100 ms; cyttsp5_init :284 drives
   the line HIGH at init; live dmesg:4052 proves this ran). Our
   ladder pulsed HIGH 10 ms and LEFT THE LINE LOW = the IC held in
   reset through every transaction since 0177 - exactly the clean
   bit-0-everywhere signature (an IC in reset never ACKs).
2. THE LDO VSET SELECTORS: the stock writes LDO4 = 1.8 V (reg 0x42,
   mask 0x07, index 3) and LDO17 = 2.8 V (reg 0x4E, index 2) BEFORE
   the enable bit (hisi_regulator.c:196-198; the tables
   hisi_6555v100_pmic.dtsi:70-73/165-168, script-verified in
   work/evidence-padmux-arithmetic.md). Our port never wrote them -
   the VSET = the bootloader's leftover (possibly the lowest
   voltage = an underpowered IC).
3. THE IOMCU RESET PULSE: the stock i2c driver pulses the
   controller's reset at probe (hisi_i2c_designware.c:139-153,966):
   assert = BIT(5) -> 0xFFD7E020, poll 0xFFD7E028 BIT(5), deassert =
   BIT(5) -> 0xFFD7E024. Our port never did.

THIS PATCH replicates all three, in the stock order (the controller
reset -> the rails with VSET -> the pads (0182) -> the VENDOR-polarity
gpio reset -> the 0183 scan -> the ladder), keeping the 0183 scan as
the classifier. The SPKLEN hypothesis is DROPPED (at our 100 kHz STD
mode the FS spike filter does not gate the bus - the research); the
pinconf hypothesis is DROPPED (the stock net cfg for gpio187/188 = 0
= identical to our observed cfg=0; the bus pull-ups are
board-external).

Falsifier ladder (the next pratouchreset=1 boot): the scan's
classified print after the three fixes - ACKs appearing (especially
0x1c) = the bring-up was the root cause; still 112 clean NACKs = the
remaining causes are the board's external pull-ups/the IC itself.
The expected intermediate signature if ONLY the reset fix matters:
the BL write ACKs (err=0) and the desc read fails err=60 (the
CMD_READ latent bug - never pushed - is unfixed by design; that
signature NAMES 0185).

Marker asserted in CI (direct yml commit): 'PRA touch: iomcu reset
pulled'.
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci184/post0183/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0184-pra-bringup-replication.patch"
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

def replace_block(lines, anchor, new, tag):
    i = anchor_unique(lines, anchor, tag)
    return lines[:i] + new + lines[i+len(anchor):], f"{tag}: replaced @ line {i+1}"

pt = read(f"{BASE}/{TARGET}")
log = []

# [1] the IOMCU pulse block, FIRST in the ladder (before the rails)
pt, m = insert_before(pt, [
    "\t/* 0180: the IC's rails - VCI = LDO17, VDDIO = LDO4 (hi6555).",
], [
    "\t/* 0184: the IOMCU reset pulse - the stock i2c driver pulses",
    "\t * the controller's reset at probe (hisi_i2c_designware.c:",
    "\t * 139-153, :966): assert = BIT(5) -> 0xFFD7E020, poll",
    "\t * 0xFFD7E028 BIT(5) until set, deassert = BIT(5) ->",
    "\t * 0xFFD7E024, poll until clear. The port never did this. The",
    "\t * pulse resets the DW registers to defaults: pra_tar = 0",
    "\t * forces the ladder's re-setup (the scan's setup runs after",
    "\t * it too). */",
    "\t{",
    "\t\tvm_offset_t iomcu = ml_io_map(0xFFD7E000ULL, 0x1000u);",
    "\t\tunsigned i;",
    "\t\tuint32_t st = 0;",
    "\t\tif (!iomcu) {",
    "\t\t\tpra_rst_fail++;",
    "\t\t\tprintf(\"PRA touch: iomcu map failed, the reset rung \"",
    "\t\t\t\t    \"aborted\\n\");",
    "\t\t\treturn;",
    "\t\t}",
    "\t\tpra_touch_wr32(iomcu, 0x020u, 0x20u);   /* assert BIT(5) */",
    "\t\tfor (i = 0; i < PRA_I2C_POLLS; i++) {",
    "\t\t\tst = pra_touch_rd32(iomcu, 0x028u);",
    "\t\t\tif (st & 0x20u) {",
    "\t\t\t\tbreak;",
    "\t\t\t}",
    "\t\t}",
    "\t\tpra_touch_wr32(iomcu, 0x024u, 0x20u);   /* deassert */",
    "\t\tfor (i = 0; i < PRA_I2C_POLLS; i++) {",
    "\t\t\tst = pra_touch_rd32(iomcu, 0x028u);",
    "\t\t\tif (!(st & 0x20u)) {",
    "\t\t\t\tbreak;",
    "\t\t\t}",
    "\t\t}",
    "\t\tprintf(\"PRA touch: iomcu reset pulsed, status=%08x\\n\", st);",
    "\t\tpra_tar = 0;",
    "\t}",
], "[1] the IOMCU pulse block")
log.append(m)

# [2] the VSET RMWs, before the enable RMWs (inside the rails block)
pt, m = insert_before(pt, [
    "\t\tif ((ldo4 & 1u) == 0u) {",
], [
    "\t\t/* 0184: the VSET selectors - the stock writes LDO4 =",
    "\t\t * 1.8 V (reg 0x42, mask 0x07, index 3) and LDO17 = 2.8 V",
    "\t\t * (reg 0x4E, index 2) BEFORE the enable bit (the vendor",
    "\t\t * regulator sequence, hisi_regulator.c:196-198; the tables",
    "\t\t * hisi_6555v100_pmic.dtsi:70-73/165-168, script-verified in",
    "\t\t * work/evidence-padmux-arithmetic.md). Our port never",
    "\t\t * wrote them - the VSET = the bootloader's leftover. The",
    "\t\t * masked RMW mirrors hisi_pmic_rmw. */",
    "\t\tvset = pra_touch_rd32(pmic, 0x108u);",
    "\t\tpra_touch_wr32(pmic, 0x108u, (vset & ~0x7u) | 3u);",
    "\t\tvset = pra_touch_rd32(pmic, 0x138u);",
    "\t\tpra_touch_wr32(pmic, 0x138u, (vset & ~0x7u) | 2u);",
    "\t\tprintf(\"PRA touch: rails vset: ldo4=%08x ldo17=%08x\\n\",",
    "\t\t    pra_touch_rd32(pmic, 0x108u),",
    "\t\t    pra_touch_rd32(pmic, 0x138u));",
], "[2] the VSET RMWs")
log.append(m)

# [3] the rails-locals: vset
pt, m = replace_block(pt, [
    "\t\tuint32_t vbus, ldo4, ldo17;",
], [
    "\t\tuint32_t vbus, ldo4, ldo17, vset;",
], "[3] the rails locals")
log.append(m)

# [4] the stage-1 polarity rewrite (the vendor shape)
pt, m = replace_block(pt, [
    "\tdir = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DIR_OFF, dir | PRA_TOUCH_RST_DIR_BIT);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DIR_BIT) == 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 dir readback failed dir=%x\\n\",",
    "\t\t    v);",
    "\t\treturn;",
    "\t}",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF, PRA_TOUCH_RST_DAT_BIT);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DAT_BIT) == 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 assert readback failed \"",
    "\t\t    \"dat=%x\\n\", v);",
    "\t\treturn;",
    "\t}",
    "\t/* Reset pulse: mainline needs >= 10 us (cyttsp5.c:881); a 10 ms",
    "\t * tsleep is far above that. */",
    "\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
    "\t    pra_touch_ms_ticks(10u));",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF, 0);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DAT_BIT) != 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 deassert readback failed \"",
    "\t\t    \"dat=%x\\n\", v);",
    "\t\treturn;",
    "\t}",
    "\t/* Device-up delay: 20 ms (mainline cyttsp5.c:885-886). */",
    "\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
    "\t    pra_touch_ms_ticks(20u));"], [
    "\t/* 0184: the VENDOR polarity (cyttsp5_platform.c:236-249 xres",
    "\t * + :284 init): the line IDLES HIGH and the reset pulse is",
    "\t * (the direction stage is kept from the previous ladder:",
    "\t * dir read, the output-enable RMW, its readback - the round-1",
    "\t * F2 fix: the pad is driven/verified as an output) */",
    "\tdir = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DIR_OFF,",
    "\t    dir | PRA_TOUCH_RST_DIR_BIT);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DIR_BIT) == 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 dir readback failed \"",
    "\t\t\t    \"dir=%x\\n\", v);",
    "\t\treturn;",
    "\t}",
    "\t * LOW - the first draft left it LOW = the IC held in reset",
    "\t * through every transaction (the universal NACK, boots",
    "\t * T5-T7). The vendor shape: HIGH 20 ms -> LOW 40 ms -> HIGH",
    "\t * 100 ms, the line ENDS HIGH. Every stage readback-verified",
    "\t * per the existing pattern. */",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF,",
    "\t    PRA_TOUCH_RST_DAT_BIT);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DAT_BIT) == 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 idle-high readback \"",
    "\t\t\t    \"failed dat=%x\\n\", v);",
    "\t\treturn;",
    "\t}",
    "\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
    "\t    pra_touch_ms_ticks(20u));",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF, 0);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DAT_BIT) != 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 low-pulse readback \"",
    "\t\t\t    \"failed dat=%x\\n\", v);",
    "\t\treturn;",
    "\t}",
    "\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
    "\t    pra_touch_ms_ticks(40u));",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF,",
    "\t    PRA_TOUCH_RST_DAT_BIT);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DAT_BIT) == 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 idle restore readback \"",
    "\t\t\t    \"failed dat=%x\\n\", v);",
    "\t\treturn;",
    "\t}",
    "\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
    "\t    pra_touch_ms_ticks(100u));",
    "\tprintf(\"PRA touch: reset gpio18.1 done dir=%x dat=%x (the \"",
    "\t\t    \"line idles HIGH)\\n\", dir, v);",
], "[4] the vendor-polarity reset")
log.append(m)

header = """pra: 0184 - replicate the stock bring-up: the reset polarity (idle HIGH, pulse LOW 40 ms), the LDO VSET selectors, the IOMCU reset pulse

work/driver-bringup-research-2026-11-19.md + boot T7 (ring48): the
reverse-engineered stock bring-up (the vendor cyttsp5 stack fetched
to work/rvr/) differs from our ladder in three verified deltas:
(1) the reset gpio polarity - the vendor idles gpio145 HIGH and
pulses LOW 40 ms (cyttsp5_platform.c:236-249, :284); our ladder left
the line LOW = the IC held in reset through every transaction (the
universal clean-NACK signature, boots T5-T7); (2) the LDO VSET
selectors - the stock writes LDO4 = 1.8 V and LDO17 = 2.8 V before
the enable bit; our port never wrote them; (3) the IOMCU reset pulse
(0xFFD7E020/24/28 BIT(5)) - never done by us. The SPKLEN hypothesis
is DROPPED (at 100 kHz STD the FS spike filter does not gate); the
pinconf hypothesis is DROPPED (the stock net cfg = 0 = ours).

This patch replicates all three in the stock order (the controller
reset -> the rails with VSET -> the pads (0182) -> the VENDOR-polarity
gpio reset -> the 0183 scan -> the ladder), keeping the scan as the
classifier. The expected intermediate signature if only the reset
polarity matters: the BL write ACKs (err=0) and the desc read fails
err=60 (the CMD_READ latent bug, unfixed by design - that signature
NAMES 0185).

Marker asserted in CI (direct yml commit): 'PRA touch: iomcu reset
pulled'.
"""

# [5] the 0183 scan-printf fix: join the literals (the base's
# separator comma passed the second literal as an argument - ring48's
# garbled line; the falsifier's scan verdicts need the print)
pt, m = replace_block(pt, [
    "\t\t\tprintf(\"PRA i2c scan: %u ACK, %u clean NACK, %u \",",
    "\t\t\t\t\"anomalies, %u wedged of 112: [%s]\\n\", ackn,",
], [
    "\t\t\tprintf(\"PRA i2c scan: %u ACK, %u clean NACK, %u \"",
    "\t\t\t\t\"anomalies, %u wedged of 112: [%s]\\n\", ackn,",
], "[5] the scan-printf concatenation fix")
log.append(m)

# [6] the pull-up experiment (the no-pull-up hypothesis is live)
pt, m = insert_before(pt, [
    "\t\tprintf(\"PRA touch: i2c pads: sda=%08x scl=%08x sdacfg=%08x \"",
], [
    "\t\tif (sdacfg != 0u && (sdacfg & 1u) != 0u) {",
    "\t\t\tprintf(\"PRA touch: i2c pads: pull-up already set\\n\");",
    "\t\t} else {",
    "\t\t\t/* 0184: the pull-up EXPERIMENT - the research proved cfg",
    "\t\t\t * bit0 = the pull-up enable (the <1 1 0 1> entries); the",
    "\t\t\t * bus-dead verdict (ring48: 112 clean NACKs) makes the",
    "\t\t\t * no-pull-up hypothesis live. Set bit0 on both cfg regs,",
    "\t\t\t * readback. */",
    "\t\t\tpra_touch_wr32(pmx, PRA_TOUCH_SDA_CFG_OFF,",
    "\t\t\t    sdacfg | 1u);",
    "\t\t\tpra_touch_wr32(pmx, PRA_TOUCH_SCL_CFG_OFF,",
    "\t\t\t    sclcfg | 1u);",
    "\t\t\tsdacfg = pra_touch_rd32(pmx, PRA_TOUCH_SDA_CFG_OFF);",
    "\t\t\tsclcfg = pra_touch_rd32(pmx, PRA_TOUCH_SCL_CFG_OFF);",
    "\t\t\tprintf(\"PRA touch: i2c pads: pull-up experiment, \\\"",
    "\t\t\t    \\\"sdacfg=%08x sclcfg=%08x\\n\", sdacfg, sclcfg);",
    "\t\t}",
], "[6] the pull-up experiment")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "\n".join([""]) if False else header)
    f.write("\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0184")
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
i_iomcu = next(i for i, l in enumerate(pt) if "iomcu reset pulsed" in l)
i_rails = next(i for i, l in enumerate(pt) if "0180: the IC's rails" in l)
i_pads = next(i for i, l in enumerate(pt) if "0182: the i2c2 pad mux" in l)
i_scan = next(i for i, l in enumerate(pt) if "0183: the I2C bus scan" in l)
i_gpio = next(i for i, l in enumerate(pt) if "0184: the VENDOR polarity" in l)
assert i_iomcu < i_rails < i_pads < i_gpio < i_scan, \
    f"the ladder order: iomcu @{i_iomcu+1} < rails @{i_rails+1} < pads @{i_pads+1} < vendor-reset @{i_gpio+1} < scan @{i_scan+1}"
print(f"[verify] order: iomcu < rails < pads < vendor-reset < scan")
assert "vset = pra_touch_rd32(pmic, 0x108u);" in "\n".join(pt), "the LDO4 VSET RMW"
assert "(vset & ~0x7u) | 2u);" in "\n".join(pt), "the LDO17 VSET RMW (index 2 = 2.8 V)"
# the reset line ENDS HIGH: the last DAT write before the done print = DAT_BIT
i_last_write = max(i for i, l in enumerate(pt[:i_scan]) if "PRA_TOUCH_RST_DAT_OFF, 0);" in l)
i_restore = next(i for i, l in enumerate(pt) if "PRA_TOUCH_RST_DAT_OFF," in l and i > i_last_write)
assert i_restore < i_scan, "the idle-HIGH restore precedes the scan"
print("[verify] the reset line is restored HIGH before the scan")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0184 applies to the reconstructed post-0183 base")

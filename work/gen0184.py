#!/usr/bin/env python3
"""gen0184.py v2 - build xnu/patches/0184-pra-bringup-replication.patch.

Base: the post-0183 pra_touch.c, reconstructed locally
(work/ci184/post0183 = the post-0182 reconstruction + the 0183 patch
applied; 0183 touches pra_touch.c only, verified during gen0183).
The CI artifact download failed repeatedly this session on network
timeouts - the reconstruction is deterministic.

ROOT CAUSE (work/driver-bringup-research-2026-11-19.md + boot T7's
scan: 0 ACK, 112 clean NACK = the bus electrically dead): the
reverse-engineered stock bring-up differs from our ladder in THREE
verified deltas:
1. THE RESET POLARITY: the vendor idles gpio145 HIGH and pulses LOW
   40 ms (cyttsp5_platform.c:236-249 xres, :284 init - VERIFIED
   first-hand in the fetched source); our ladder left the line LOW =
   the IC held in reset through every transaction (the universal
   clean-NACK signature).
2. THE LDO VSET SELECTORS: the stock writes LDO4 = 1.8 V (reg 0x42,
   mask 0x07, index 3) and LDO17 = 2.8 V (reg 0x4E, index 2) before
   the enable bit (hisi_regulator.c:196-198; the tables
   hisi_6555v100_pmic.dtsi:70-73/165-168). Our port never did.
3. THE IOMCU RESET PULSE (0xFFD7E020/24/28 BIT(5)): never done by us.

The SPKLEN hypothesis is DROPPED (at 100 kHz STD the FS spike filter
does not gate). The pinconf hypothesis is an EXPERIMENT, not a
dropped item: cfg bit0 = the pull-up enable (the research's <1 1 0 1>
proof), the PRA product dts is absent, so 0184 sets bit0 on the two
cfg registers when they read 0 (an experiment, printed). The 0183
scan-printf concatenation bug is FIXED here (the base's separator
comma made the second literal an argument - ring48's garbled line).
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
    "\t\t\t\t\"aborted\\n\");",
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
    "\t\t * masked RMW preserves the upper lanes (the value is read",
    "\t\t * first). */",
    "\t\tvset = pra_touch_rd32(pmic, 0x108u);",
    "\t\tpra_touch_wr32(pmic, 0x108u, (vset & ~0x7u) | 3u);",
    "\t\tvset = pra_touch_rd32(pmic, 0x138u);",
    "\t\tpra_touch_wr32(pmic, 0x138u, (vset & ~0x7u) | 2u);",
    "\t\tprintf(\"PRA touch: rails vset: ldo4=%08x ldo17=%08x\\n\",",
    "\t\t    pra_touch_rd32(pmic, 0x108u),",
    "\t\t    pra_touch_rd32(pmic, 0x138u));",
], "[2] the VSET RMWs")
log.append(m)

# [2b] the rails locals: vset
pt, m = replace_block(pt, [
    "\t\tuint32_t vbus, ldo4, ldo17;",
], [
    "\t\tuint32_t vbus, ldo4, ldo17, vset;",
], "[2b] the rails locals")
log.append(m)

# [3] the pull-up experiment, before the i2c-pads print
pt, m = insert_before(pt, [
    "\t\tprintf(\"PRA touch: i2c pads: sda=%08x scl=%08x sdacfg=%08x \"",
], [
    "\t\tif (sdacfg == 0u) {",
    "\t\t\t/* 0184: the pull-up EXPERIMENT - the research proved cfg",
    "\t\t\t * bit0 = the pull-up enable (the <1 1 0 1> entries); the",
    "\t\t\t * bus-dead verdict (ring48: 112 clean NACKs) makes the",
    "\t\t\t * no-pull-up hypothesis live. Set bit0 on both cfg regs,",
    "\t\t\t * readback. The stock cfg value is 0 only per the UDP",
    "\t\t\t * reference - the PRA product dts is absent, so this is",
    "\t\t\t * an experiment, not a stock replication. */",
    "\t\t\tpra_touch_wr32(pmx, PRA_TOUCH_SDA_CFG_OFF,",
    "\t\t\t    sdacfg | 1u);",
    "\t\t\tpra_touch_wr32(pmx, PRA_TOUCH_SCL_CFG_OFF,",
    "\t\t\t    sclcfg | 1u);",
    "\t\t\tsdacfg = pra_touch_rd32(pmx, PRA_TOUCH_SDA_CFG_OFF);",
    "\t\t\tsclcfg = pra_touch_rd32(pmx, PRA_TOUCH_SCL_CFG_OFF);",
    "\t\t\tprintf(\"PRA touch: i2c pads: pull-up experiment, \"",
    "\t\t\t    \"sdacfg=%08x sclcfg=%08x\\n\", sdacfg, sclcfg);",
    "\t\t}",
], "[3] the pull-up experiment")
log.append(m)

# [4] the vendor-polarity reset (replace the whole stage-1 sequence)
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
    "\t    pra_touch_ms_ticks(20u));",
    "\tprintf(\"PRA touch: reset gpio18.1 done dir=%x dat=%x\\n\", dir, v);",
], [
    "\t/* 0184: the VENDOR polarity (cyttsp5_platform.c:236-249 xres +",
    "\t * :284 init): the line IDLES HIGH and the reset pulse is LOW -",
    "\t * the first draft left it LOW = the IC held in reset through",
    "\t * every transaction (the universal NACK, boots T5-T7). The",
    "\t * vendor shape: HIGH 20 ms -> LOW 40 ms -> HIGH 100 ms, the",
    "\t * line ENDS HIGH. Every stage readback-verified per the",
    "\t * existing pattern; the direction stage is kept. */",
    "\tdir = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DIR_OFF, dir | PRA_TOUCH_RST_DIR_BIT);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DIR_BIT) == 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 dir readback failed dir=%x\\n\",",
    "\t\t    v);",
    "\t\treturn;",
    "\t}",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF,",
    "\t    PRA_TOUCH_RST_DAT_BIT);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DAT_BIT) == 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 idle-high readback failed \"",
    "\t\t    \"dat=%x\\n\", v);",
    "\t\treturn;",
    "\t}",
    "\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
    "\t    pra_touch_ms_ticks(20u));",
    "\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF, 0);",
    "\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
    "\tif ((v & PRA_TOUCH_RST_DAT_BIT) != 0) {",
    "\t\tpra_rst_fail++;",
    "\t\tprintf(\"PRA touch: reset gpio18.1 low-pulse readback failed \"",
    "\t\t    \"dat=%x\\n\", v);",
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
    "\t\t    \"failed dat=%x\\n\", v);",
    "\t\treturn;",
    "\t}",
    "\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
    "\t    pra_touch_ms_ticks(100u));",
    "\tprintf(\"PRA touch: reset gpio18.1 done dir=%x dat=%x (the line \"",
    "\t\t    \"idles HIGH)\\n\", dir, v);",
], "[4] the vendor-polarity reset")
log.append(m)

# [5] the 0183 scan-printf concatenation fix
pt, m = replace_block(pt, [
    "\t\t\tprintf(\"PRA i2c scan: %u ACK, %u clean NACK, %u \",",
    "\t\t\t\t\"anomalies, %u wedged of 112: [%s]\\n\", ackn,",
], [
    "\t\t\tprintf(\"PRA i2c scan: %u ACK, %u clean NACK, %u \"",
    "\t\t\t\t\"anomalies, %u wedged of 112: [%s]\\n\", ackn,",
], "[5] the scan-printf concatenation fix")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = open(f"{REPO}/work/gen0184-header.txt", encoding="utf-8").read()
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
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
i_vendor = next(i for i, l in enumerate(pt) if "0184: the VENDOR polarity" in l)
i_scan = next(i for i, l in enumerate(pt) if "0183: the I2C bus scan" in l)
assert i_iomcu < i_rails < i_pads < i_vendor < i_scan, \
    f"the ladder order: iomcu @{i_iomcu+1} < rails @{i_rails+1} < pads @{i_pads+1} < vendor-reset @{i_vendor+1} < scan @{i_scan+1}"
print(f"[verify] order: iomcu < rails < pads < vendor-reset < scan")
assert "vset = pra_touch_rd32(pmic, 0x108u);" in "\n".join(pt), "the LDO4 VSET RMW"
assert "(vset & ~0x7u) | 2u);" in "\n".join(pt), "the LDO17 VSET RMW (index 2 = 2.8 V)"
assert 'dir = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);' in "\n".join(pt), \
    "the dir read survives (the round-1 F1 fix)"
# the reset line ENDS HIGH: the last DAT write before the scan = DAT_BIT
scan_text = "\n".join(pt[i_vendor:i_scan])
last_dat = [l for l in scan_text.split("\n") if "PRA_TOUCH_RST_DAT_OFF" in l]
last_dat_idx = max(i for i, l in enumerate(pt[:i_scan])
                   if "pra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF," in l)
assert "PRA_TOUCH_RST_DAT_BIT);" in pt[last_dat_idx] or \
       "PRA_TOUCH_RST_DAT_BIT);" in pt[last_dat_idx + 1], \
    "the last DAT write before the scan restores DAT_BIT (idle HIGH)"
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0184 applies to the reconstructed post-0183 base")

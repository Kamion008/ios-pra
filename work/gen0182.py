#!/usr/bin/env python3
"""gen0182.py - build xnu/patches/0182-pra-i2c-padmux.patch.

Base: the CI-compiled tree from run 44393972634
(work/ci182/post0181) - the post-0181 state for pra_touch.c, i.e. the
source of the kernel currently flashed (boot T5's diag kernel).

ROOT CAUSE (boot T5, ring46 - the 0181 diag answered): the i2c2
controller is live and correctly configured (tar=0000001c IN THE
ENGINE, con=00000063, en=01/enstat=01, COMP re-read live) and BOTH
transactions still return ABRT bit 0 = the 7-bit TARGET ADDRESS was
NACKed. Every controller-side hypothesis is falsified. The remaining
fork: a deaf IC, or the bus wiring. The wiring branch has a concrete,
unwritten suspect: the i2c2 SDA/SCL pad registers (gpio187/188)
live in TWO windows (the dtsi's per-pin offsets are per-entry facts,
not a formula - the pmx1 bank is even packed after the absent
gpio191): the MUX at 0xFFF11000+0x024/0x028 (func 0x1 = I2C, 0x0 =
idle; hi6250_udp_default_pin.dtsi:714-725, inside the
pinmux@fff11000 node :650-939) and the CFG at 0xFFF11800+0x02C/0x030
(the pull/drive fields, stock value 0; :2477-2480, :2492-2495, the
bank base 176). Both windows live (iomem.txt:92-93). The port NEVER
writes them: pads not at the stock I2C function = the controller
drives into nowhere = the universal address NACK - exactly the
observed signature. (The round-2 review caught the first draft
targeting pmx0 = gpio012/013's registers; the round-4 review caught
the cfg reads hitting gpio189/190's mux - both fixed.)

This patch: the 0180 pattern - map pmx0, read + print the four pad
registers, write the stock func value (0x1) PER-PAD only to a pad
whose read value differs, readback, abort the rung on a failed
readback. The cfg registers stay read-only (their pull/drive fields
gate signal quality; the bus's pull-up arrangement is UNKNOWN and the
prints will show what the bootloader left). The ladder then reruns
against a possibly fixed bus: pads already at 0x1 = the wiring branch
falsified (IC-side next); pads moved to 0x1 = the ladder's ACK/NACK
verdict becomes real.
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci182/post0181/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0182-pra-i2c-padmux.patch"
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

# [1] the pmx0 pad-mux defines, after the reset-bank defines
pt, m = insert_before(pt, [
    "/*",
    " * BL_LAUNCH_APP output-register frame (mainline cyttsp5.c:34-37,609-623):",
], [
    "/*",
    " * 0182: the i2c2 pad registers live in TWO windows (the dtsi's",
    " * per-pin offsets are per-entry facts, not a formula - the pmx1",
    " * bank is even PACKED after the absent gpio191: gpio192 = 0x034,",
    " * not 0x38):",
    " * - the MUX: gpio187_pmx_func = <0x024 0x1> and gpio188_pmx_func",
    " *   = <0x028 0x1> (hi6250_udp_default_pin.dtsi:714-725; the",
    " *   entries sit INSIDE the pinmux@fff11000 node :650-939):",
    " *   func 0x1 = I2C, 0x0 = idle;",
    " * - the CFG: gpio187_cfg_func = <0x02C 0> and gpio188_cfg_func =",
    " *   <0x030 0> (:2477-2480, :2492-2495; bank base 176: gpio176_cfg",
    " *   = 0x000, gpio177 = 0x004, gpio178 = 0x008) - the pull/drive",
    " *   fields, stock value 0. The cfg entries belong to the",
    " *   pinmux@fff11800 node, whose addresses 0xFFF1182C/0xFFF11830",
    " *   are REACHABLE from the pmx1 map: 0xFFF11000 + 0x82C =",
    " *   0xFFF1182C (computed) - so ONE map of 0xFFF11000/0x1000",
    " *   covers both register groups (the round-6 review's nit: the",
    " *   second map was redundant).",
    " * Both windows are live (iomem.txt:92-93: fff11000-fff110ab,",
    " * fff11800-fff118bb). The port never writes them anywhere in the",
    " * tree (grep-verified across post0181) - pads not at the stock",
    " * I2C function = the controller drives into nowhere = consistent",
    " * with the observed address NACK (the round-6 review: an",
    " * unmuxed pad's idle level is NOT known - it can equally read",
    " * low, so the signature is consistent-with, not exactly).",
    " */",
    "#define PRA_TOUCH_PMX_BASE      0xFFF11000ULL   /* the mux AND the",
    "	 * cfg registers (0xFFF1182C/0xFFF11830 = base + 0x82C/0x830)",
    "	 * both live inside this 4 KiB span */",
    "#define PRA_TOUCH_PMX_SIZE      0x1000u",
    "#define PRA_TOUCH_SDA_PMX_OFF   0x024u",
    "#define PRA_TOUCH_SCL_PMX_OFF   0x028u",
    "#define PRA_TOUCH_SDA_CFG_OFF   0x82Cu  /* = 0xFFF1182C, the",
    "	 * pinmux@fff11800 window's 0x02C; read-only here */",
    "#define PRA_TOUCH_SCL_CFG_OFF   0x830u  /* = 0xFFF11830; read-only",
    "	 * here */",
    "#define PRA_TOUCH_I2C_FUNC      0x1u",
    "",
], "[1] the pmx0 pad-mux defines")
log.append(m)

# [2] the padmux block, after the 0180 rails block, before stage 1
pt, m = insert_before(pt, [
    "\t/* 1. gpio18.1: set the DIR bit (pl061 pin direction, 1 = output)",
], [
    "\t/* 0182: the i2c2 pad mux in the PMX1 window at 0xFFF11000",
    "\t * (see the define block above). Read +",
    "\t * print all four pad registers; if a pad's mux value differs",
    "\t * from the stock I2C function, write THAT pad and readback - the ladder",
    "\t * then reruns against a possibly fixed bus. The cfg registers",
    "\t * stay read-only: they gate signal quality (pull/drive), not",
    "\t * connectivity, and the stock func value is 0 anyway. */",
    "\t{",
    "\t\tvm_offset_t pmx = ml_io_map((vm_offset_t)PRA_TOUCH_PMX_BASE,",
    "\t\t    (vm_offset_t)PRA_TOUCH_PMX_SIZE);",
    "\t\tuint32_t sda, scl, sdacfg, sclcfg;",
    "\t\tif (!pmx) {",
    "\t\t\tpra_rst_fail++;",
    "\t\t\tprintf(\"PRA touch: pmx map failed, the reset rung \"",
    "\t\t\t    \"aborted\\n\");",
    "\t\t\treturn;",
    "\t\t}",
    "\t\tsda = pra_touch_rd32(pmx, PRA_TOUCH_SDA_PMX_OFF);",
    "\t\tscl = pra_touch_rd32(pmx, PRA_TOUCH_SCL_PMX_OFF);",
    "\t\tsdacfg = pra_touch_rd32(pmx, PRA_TOUCH_SDA_CFG_OFF);",
    "\t\tsclcfg = pra_touch_rd32(pmx, PRA_TOUCH_SCL_CFG_OFF);",
    "\t\tprintf(\"PRA touch: i2c pads: sda=%08x scl=%08x sdacfg=%08x \"",
    "\t\t    \"sclcfg=%08x\\n\", sda, scl, sdacfg, sclcfg);",
    "\t\tif (sda == PRA_TOUCH_I2C_FUNC && scl == PRA_TOUCH_I2C_FUNC) {",
    "\t\t\tprintf(\"PRA touch: i2c pads already muxed to I2C, no \"",
    "\t\t\t    \"write\\n\");",
    "\t\t} else {",
    "\t\t\t/* per-pad: never write a pad that already reads the",
    "\t\t\t * stock function (the round-1 review's refuted-falsifier",
    "\t\t\t * fix - a write lands only on the differing pad) */",
    "\t\t\tif (sda != PRA_TOUCH_I2C_FUNC) {",
    "\t\t\t\tpra_touch_wr32(pmx, PRA_TOUCH_SDA_PMX_OFF,",
    "\t\t\t\t    PRA_TOUCH_I2C_FUNC);",
    "\t\t\t}",
    "\t\t\tif (scl != PRA_TOUCH_I2C_FUNC) {",
    "\t\t\t\tpra_touch_wr32(pmx, PRA_TOUCH_SCL_PMX_OFF,",
    "\t\t\t\t    PRA_TOUCH_I2C_FUNC);",
    "\t\t\t}",
    "\t\t\tsda = pra_touch_rd32(pmx, PRA_TOUCH_SDA_PMX_OFF);",
    "\t\t\tscl = pra_touch_rd32(pmx, PRA_TOUCH_SCL_PMX_OFF);",
    "\t\t\tif (sda != PRA_TOUCH_I2C_FUNC ||",
    "\t\t\t    scl != PRA_TOUCH_I2C_FUNC) {",
    "\t\t\t\tpra_rst_fail++;",
    "\t\t\t\tprintf(\"PRA touch: i2c pad mux write failed, the \"",
    "\t\t\t\t    \"reset rung aborted\\n\");",
    "\t\t\t\treturn;",
    "\t\t\t}",
    "\t\t\t/* the post-write VALUES printed: a whole-word write that",
    "\t\t\t * clobbered upper register bits would read back 1 and",
    "\t\t\t * pass silently otherwise (round-6 K4) */",
    "\t\t\tprintf(\"PRA touch: i2c pads muxed to I2C func, readback \"",
    "\t\t\t    \"sda=%08x scl=%08x\\n\", sda, scl);",
    "\t\t}",
    "\t}",
    "\t/* the gpio18.1 stage follows: the bus wiring is now as ready as",
    "\t * this rung can make it */",
], "[2] the padmux block")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0182 - the i2c2 pad mux (gpio187/188 -> I2C func 0x1) before the ladder

work/i2c-research-2026-11-18.md + boot T5 (ring46): the 0181 diag
falsified every controller-side hypothesis - tar=0000001c IN THE
ENGINE (the setup's write landed), con=00000063, en=01/enstat=01,
COMP re-read live, and BOTH transactions still return ABRT bit 0 =
the 7-bit target address was NACKed. The remaining fork: a deaf IC,
or the bus wiring.

The wiring branch has a concrete, never-written suspect: the i2c2
SDA/SCL pad registers (gpio187/188) - the MUX words at
0xFFF11000+0x024/0x028 (gpio187_pmx_func = <0x024 0x1>,
gpio188_pmx_func = <0x028 0x1>, hi6250_udp_default_pin.dtsi:714-725,
inside the pinmux@fff11000 node :650-939; func 0x1 = I2C, 0x0 =
idle) and the CFG words at 0xFFF1182C/0xFFF11830 (gpio187_cfg_func =
<0x02C 0>, gpio188_cfg_func = <0x030 0>, :2477-2480/:2492-2495; the
pull/drive fields, stock value 0; the cfg entries belong to the
pinmux@fff11800 node, REACHABLE from the pmx1 map: 0xFFF11000 +
0x82C = 0xFFF1182C). Both windows are live (live/iomem.txt:92-93:
fff11000-fff110ab, fff11800-fff118bb). The dtsi's per-pin offsets
are per-entry facts, not a formula (the bank has gaps: gpio222's
actual 0x0a8 sits 8 bytes below the linear 0xb0). No file in the
tree writes these windows (grep-verified across post0181): pads not
at the stock I2C function = the controller drives into nowhere -
CONSISTENT WITH the observed address NACK (the round-6 review: an
unmuxed pad's idle level is unknown - it can equally read low), and
consistent with the reset pin working: pl061's own bank needed no
pinmux write for gpio18.1's DAT readback. The first draft targeted
pmx0 = gpio012/013's registers (the round-2 review); the second
draft read the cfg from gpio189/190's mux (the round-4 review) -
both fixed.

This patch (the 0180 pattern): map 0xFFF11000/0x1000 (ONE map
covering both register groups: the mux at +0x024/+0x028, the cfg at
+0x82C/+0x830), read + print the four pad registers, write the
stock func value 0x1 PER-PAD to the mux registers ONLY where the
read value differs, readback - the POST-WRITE VALUES printed (a
whole-word write that clobbered upper register bits would otherwise
pass invisibly; pinctrl-single,function-mask is absent from the
dtsi, so the stock driver's own i2c2 bring-up write is the same
whole-word form we replicate) - and abort the rung on a failed
readback. The cfg registers stay read-only (the pull/drive fields -
the bus's pull-up arrangement is UNKNOWN and the prints will show
what the bootloader left). Then the existing ladder reruns against
a possibly fixed bus.

Decodes (the next pratouchreset=1 boot): 'i2c pads: sda=...00000001
scl=...00000001' + 'already muxed' = the wiring branch falsified -
the NACK means a deaf IC at 0x1c (mode/power rung next); any other
value + 'muxed to I2C func, readback OK' = the pads WERE unmuxed and
are now fixed - the ladder's ACK/NACK verdict becomes real;
'pad mux write failed' = the mux write did not take (a deeper block).

Marker asserted in CI (direct yml commit): 'PRA touch: i2c pads:'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0182")
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

# structural assertions: the padmux block sits between the rails block
# and the gpio stage; the marker string appears exactly once
i_pads = next(i for i, l in enumerate(pt) if "PRA touch: i2c pads:" in l)
i_rails = next(i for i, l in enumerate(pt) if "rails on: VDDIO VCI" in l)
i_gpio = next(i for i, l in enumerate(pt) if "1. gpio18.1: set the DIR" in l)
assert i_rails < i_pads < i_gpio, \
    f"the padmux block @{i_pads+1} must sit between the rails @{i_rails+1} and the gpio stage @{i_gpio+1}"
print(f"[verify] rails @{i_rails+1} < padmux @{i_pads+1} < gpio stage @{i_gpio+1}")
assert sum(1 for l in pt if "PRA touch: i2c pads:" in l) == 1, "the marker string must appear exactly once"
assert sum(1 for l in pt if "pra_touch_wr32(pmx," in l) == 2, "exactly two mux writes"
assert sum(1 for l in pt if "pra_touch_rd32(pmx," in l) == 6, "6 reads: 2 mux + 2 cfg + 2 readbacks"
assert "PRA_TOUCH_SDA_CFG_OFF   0x82Cu" in "\n".join(pt) or any("0x82Cu" in l for l in pt), "the cfg offsets are the in-window 0x82C/0x830"
assert "readback \"" in "\n".join(pt) and "sda=%08x scl=%08x" in "\n".join(pt), "the readback prints the post-write values"
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0182 applies to the post-0181 CI base (run 44393972634)")

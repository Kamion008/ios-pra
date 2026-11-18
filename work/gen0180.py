#!/usr/bin/env python3
"""gen0180.py - build xnu/patches/0180-pra-touch-rails-enable.patch.

Base: the CI-compiled tree from run 44358321437 (/tmp/bt0180) - post-0179
state for pra_touch.c (0178's DAT window fix present: "reset gpio18.1
done" in boot T3's ring44).

ROOT CAUSE (work/rails-research-2026-11-18.md, VERIFIED): the IC's rails -
VCI = LDO17, VDDIO = LDO4 (hi6555) - were never enabled; the PMIC access
is 0xFFF34000 + (reg << 2); LDO4's enable = 0xFFF34064 bit 0 (reg 0x19),
LDO17's = 0xFFF34094 bit 0 (reg 0x25); cross-sourced from two dts files +
the GPL hisi_pmic driver. ring44: the reset line worked (0178's window
fix) but BL_LAUNCH_APP + the descriptor address-NACKed - an unpowered IC
NACKs everything.
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = "/tmp/bt0180/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0180-pra-touch-rails-enable.patch"
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

NEW = [
    "\t/* 0180: the IC's rails - VCI = LDO17, VDDIO = LDO4 (hi6555).",
    "\t * The PMIC registers: 0xFFF34000 + (reg << 2) (the hisi_pmic",
    "\t * driver convention, VERIFIED against hisi_6555v100_pmic.dtsi:",
    "\t * 62-68,157-163 + hisi_6250_lowpm.dtsi:645-652 + the GPL",
    "\t * hisi_pmic driver). LDO4's enable = 0xFFF34064 bit 0 (reg",
    "\t * 0x19), LDO17's = 0xFFF34094 bit 0 (reg 0x25). An unpowered IC",
    "\t * address-NACKs everything (ring44: BL_LAUNCH_APP write failed",
    "\t * err=6 AFTER the reset line worked - the rails were never",
    "\t * enabled). Read both + the vbus falsification anchor (reg",
    "\t * 0x18 bit 1 = bus alive), print, enable if off, readback. */",
    "\t{",
    "\t\tvm_offset_t pmic = ml_io_map(0xFFF34000ULL, 0x1000u);",
    "\t\tuint32_t vbus, ldo4, ldo17;",
    "\t\tif (!pmic) {",
    "\t\t\tpra_rst_fail++;",
    "\t\t\tprintf(\"PRA touch: pmic map failed, the reset rung "
    "\t\t\t    aborted\\n\");",
    "\t\t\treturn;",
    "\t\t}",
    "\t\t/* raw words printed: an all-0xFF or all-0x00 pattern across the",
    "\t\t * three reads = the window is not live from our kernel entry,",
    "\t\t * and every conclusion below would be void (the access-method",
    "\t\t * problem, not the rails). */",
    "\t\tvbus = pra_touch_rd32(pmic, 0x18u);",
    "\t\tldo4 = pra_touch_rd32(pmic, 0x64u);",
    "\t\tldo17 = pra_touch_rd32(pmic, 0x94u);",
    "\t\tprintf(\"PRA touch: rails raw: vbus=%08x ldo4=%08x ldo17=%08x\\n\",",
    "\t\t    vbus, ldo4, ldo17);",
    "\t\tif (vbus == ldo4 && ldo4 == ldo17) {",
    "\t\t\t/* three DIFFERENT registers reading identical values = the",
    "\t\t\t * window is dead from our kernel entry (the access-method",
    "\t\t\t * problem); the per-register 0/0xff checks below are the",
    "\t\t\t * legitimate OFF states, not proof of a dead window. */",
    "\t\t\tpra_rst_fail++;",
    "\t\t\tprintf(\"PRA touch: PMIC window not live, the reset rung "
    "\t\t\t    aborted\\n\");",
    "\t\t\treturn;",
    "\t\t}",
    "\t\t/* the enables: the hisi_pmic driver writes the value in the",
    "\t\t * low byte of the 32-bit slot (the upper lanes are ignored by",
    "\t\t * the PMIC's 8-bit bus) - mirror that convention, RMW the 8-bit",
    "\t\t * register so the eco bit is preserved. */",
    "\t\tif ((ldo4 & 1u) == 0u) {",
    "\t\t\tpra_touch_wr32(pmic, 0x64u, (ldo4 & 0xffu) | 1u);",
    "\t\t\tldo4 = pra_touch_rd32(pmic, 0x64u);",
    "\t\t}",
    "\t\tif ((ldo17 & 1u) == 0u) {",
    "\t\t\tpra_touch_wr32(pmic, 0x94u, (ldo17 & 0xffu) | 1u);",
    "\t\t\tldo17 = pra_touch_rd32(pmic, 0x94u);",
    "\t\t}",
    "\t\tif ((ldo4 & 1u) == 0u || (ldo17 & 1u) == 0u) {",
    "\t\t\tpra_rst_fail++;",
    "\t\t\tprintf(\"PRA touch: rail enable readback failed, the reset "
    "\t\t\t    rung aborted (the rails next)\\n\");",
    "\t\t\treturn;",
    "\t\t}",
    "\t\tprintf(\"PRA touch: rails on: VDDIO VCI enabled, 20 ms ramp\\n\");",
    "\t\t(void)tsleep(&pra_touch_chan, PZERO, \"prarails\",",
    "\t\t    pra_touch_ms_ticks(20u));",
    "\t}",
]

# [1] the rails block, after the locals, before stage 1
pt, m = insert_before(pt, [
    "\t/* 1. gpio18.1: set the DIR bit (pl061 pin direction, 1 = output)",
], NEW, "[1] the rails enable block")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0180 - enable the touch IC's rails (LDO17/LDO4) before the reset

work/rails-research-2026-11-18.md (VERIFIED): the touch IC's rails - VCI =
LDO17, VDDIO = LDO4 (hi6555) - were never enabled by the port; the PMIC
access = 0xFFF34000 + (reg << 2); LDO4's enable = 0xFFF34064 bit 0 (reg
0x19), LDO17's = 0xFFF34094 bit 0 (reg 0x25), cross-sourced from two dts
files + the GPL hisi_pmic driver. ring44: the reset line worked (the 0178
window fix: "reset gpio18.1 done dir=2 dat=0") but BL_LAUNCH_APP and the
descriptor address-NACKed - an unpowered IC NACKs everything.

This patch: in pra_touch_reset_launch, BEFORE the gpio18.1 stage - map the
PMIC window, read the vbus falsification anchor (reg 0x18 bit 1) + both
LDO ctrl registers, print the states, enable any off rail (RMW bit 0,
readback), wait 10 ms for the ramp, then the existing reset+launch ladder
runs against a (hopefully) powered IC. All failures abort the rung via the
existing pra_rst_fail pattern.

Falsification: the vbus read (bit 1) proves the PMIC window is live; if
vbus reads plausibly and the LDO bits read 0, the rails were unpowered -
confirmed. If the enables pass but the descriptor still NACKs, the rails
are not the (only) problem - the I2C address/controller is next.

Marker asserted in CI (direct yml commit): 'PRA touch: rails vbus='.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0180")
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
i_rails = next(i for i, l in enumerate(pt) if "rails raw: vbus=" in l)
i_gpio = next(i for i, l in enumerate(pt) if "1. gpio18.1: set the DIR" in l)
assert i_rails < i_gpio, "the rails block must precede the gpio stage"
print(f"[verify] the rails block @ {i_rails+1} < the gpio stage @ {i_gpio+1}")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0180 applies to the post-0179 CI base")

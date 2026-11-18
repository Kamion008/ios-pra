#!/usr/bin/env python3
"""gen0178.py - build xnu/patches/0178-pra-touch-dat-window.patch.

Base: the CI-compiled tree from run 44190353269 (/tmp/bt0177) - post-0177
state. ROOT CAUSE (review round 1, K2, work/pkt-163249 - accepted): the
reset toggled the WRONG PL061 masked window. The defines had
PRA_TOUCH_RST_DAT_OFF = (1u*4u) = 0x4 = pin 0's window; pin 1's masked
window = 4u << 1u = 0x8. Ground truth: the bootloader's own decode -
"fingerprint,irq_gpio = fff1d008" for gpio225 = bank 28 PIN 1 (4<<1) -
the SAME pin-1 position as gpio145 = bank 18 pin 1. ring42's dat=0 was
pin 0's state read through the wrong window; pin 1 was never toggled.
(The pmx0 pinmux theory from the first 0178 draft is REFUTED by review
pkt-163249 K2: dat=0 is fully explained by the window; dropped.)
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = "/tmp/bt0177/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0178-pra-touch-dat-window.patch"
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

# [1] the DAT window: pin 1's masked address = 4 << pin = 0x8, not pin*4
pt, m = replace_block(pt, [
    "#define PRA_TOUCH_RST_DAT_OFF   (1u * 4u)       /* gpio18.1 */",
], [
    "#define PRA_TOUCH_RST_DAT_OFF   (4u << 1u)      /* gpio18.1: PL061",
    "\t * masked window for pin 1 - 4 << pin, per the bootloader's own",
    "\t * decode (\"fingerprint,irq_gpio = fff1d008\" = gpio225 = bank 28",
    "\t * PIN 1 -> offset 8; gpio145 = bank 18 pin 1, the same position).",
    "\t * The old pin*4 = 0x4 was PIN 0's window: ring42's dat=0 was read",
    "\t * through the wrong window. */",
], "[1] DAT window")
log.append(m)

# [1b] the DAT_BIT is COUPLED to the window: at the masked address 4<<pin,
# only bit N is written or returned (review round 2, K3 FAULT) - pin 1's
# level lives in bit 1 of the word, so the write value and the readback
# mask both move 0x1 -> 0x2.
pt, m = replace_block(pt, [
    "#define PRA_TOUCH_RST_DAT_BIT   0x1u            /* level in bit 0 */",
], [
    "#define PRA_TOUCH_RST_DAT_BIT   0x2u            /* pin 1's level in",
    "\t * bit 1 of the masked word (the window is 4 << pin, so bit N is",
    "\t * written and returned at bit N - review pkt-163857 K3). */",
], "[1b] DAT_BIT coupled to the window")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0178 - the touch reset toggled the WRONG PL061 masked window

ring42 (the first pratouchreset=1 boot): "reset gpio18.1 assert readback
failed dat=0" -> the descriptor NACK unchanged. The defines had
PRA_TOUCH_RST_DAT_OFF = (1u*4u) = 0x4 - PIN 0's masked window. The PL061
masked address for pin N is 4 << pin: the bootloader's own decode anchors
it ("fingerprint,irq_gpio = fff1d008" = gpio225 = bank 28 PIN 1 = offset
8), and gpio145 = bank 18 PIN 1 sits at the same position. So the reset
pulsed an unknown pin 0 for 10 ms while pin 1 was never toggled - the IC
never reset, the descriptor NACK followed.

Fix: DAT_OFF = (4u << 1u) = 0x8 AND DAT_BIT = 0x2 - the two defines are
COUPLED: at the masked window 4 << pin, only bit N is written or
returned, so the 0177 code (window 0x4 + value/mask 0x1) wrote value-bit-0
at pin 0's window and would write pin 1 LOW and read it in the wrong bit
at the corrected window (review pkt-163857 K3, FAULT). DIR (0x400, bit
0x2) already correct - ring42's DIR readback PASSED, which also proves
the bank address, the map and the clock gate are fine (the pmx0 pinmux
theory from the first 0178 draft is refuted by review pkt-163249 K2:
dat=0 is fully explained by the window). Falsifier: if the toggle at 0x8
with the value in bit 1 still reads 0, the pad is clamped or unpowered -
the touch rails (VCI=LDO17/VDDIO=LDO4, enable offsets UNKNOWN) are the
next hunt. A PASS prints "reset gpio18.1 done dir=%x dat=%x" (the base's
own line) and the ladder proceeds to BL_LAUNCH_APP.

No binary marker: a define change emits no string. The CI guard is the
apply-phase grep for this patch's filename (added to the Build step in
the same commit - the 0176 lesson).
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0178")
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
# the define sanity: the masked window for pin 1 in the patched file
i_def = next(i for i, l in enumerate(pt) if "PRA_TOUCH_RST_DAT_OFF" in l)
print(f"[verify] DAT_OFF define @ {i_def+1}: {pt[i_def].strip()[:70]}")
assert "(4u << 1u)" in pt[i_def], "the offset define did not take"
i_bit = next(i for i, l in enumerate(pt) if "PRA_TOUCH_RST_DAT_BIT" in l)
print(f"[verify] DAT_BIT define @ {i_bit+1}: {pt[i_bit].strip()[:70]}")
assert "0x2u" in pt[i_bit], "the bit define did not take"
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0178 applies to the post-0177 CI base")

#!/usr/bin/env python3
"""gen0194.py - build xnu/patches/0194-pra-touch-panel-init.patch.

Base: work/ci193/pre0193/xnu + 0193 (SweetHID.cpp only).
0194 touches iokit/Kernel/arm/hid/SweetHID.cpp only.

ROOT CAUSE (VERIFIED against the T17 kernel artifact cc83d49c):
- build.log:34742: the PRA compile line is
  -DARM64_BOARD_CONFIG_PRA -DARM64_BOARD_CONFIG_A5XELTE (BOTH).
- SweetHIDTouch::start() is therefore compiled with the
  ARM64_BOARD_CONFIG_A5XELTE arm (const pool @0x702e720 = 1080,1920,0,0).
- 0193 added fPanelW/fPanelH ONLY to the #else arm. In the compiled arm
  they are never stored (disassembly: start() has no str to [x19,#0xc0]
  or [x19,#0xc4]) and stay 0.
- touch() clamps with `x >= fPanelW ? fPanelW - 1 : x`; fPanelW = 0 gives
  `sub w9, w8, #1` = -1 and every touch prints/queues (-1,-1).
  That is exactly ring58: "PRA touch: hid inject slot=0 down x=550 y=1911"
  immediately followed by "SWEET HID: touch 0 down at -1,-1 edge".

THE FIX (0194):
1. Initialize fPanelW/fPanelH in BOTH arms. The compiled A5XELTE arm is
   the PRA panel: 1080x1920 (pra_touch.c PANEL_X_MAX/PANEL_Y_MAX and the
   framebuffer's 1080x1920 swaps), fLogical 1080x1920, zero offsets.
2. Publish the working A5 board's real surface (68x121 mm) in this arm.
   0193 had made SurfaceWidth unconditional 8655995 (132.08 mm) - that
   number came from treating the 5.2-inch DIAGONAL as the width. The
   else arm keeps 0193's 132x144 mm.
3. One-time marker "SWEET HID: panel arm" inside the compiled arm so a
   silently skipped 0194 fails the CI strings guard.

No behavior change outside SweetHIDTouch::start().
"""
import difflib
import os
import subprocess
import tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci193/pre0193/xnu"
P = f"{REPO}/xnu/patches"
P193 = f"{P}/0193-pra-touch-surface-geometry.patch"
OUT = f"{P}/0194-pra-touch-panel-init.patch"
HID = "iokit/Kernel/arm/hid"


def read(path):
    return open(path, encoding="utf-8").read().splitlines()


def find_one(lines, pred, tag):
    hits = [i for i, line in enumerate(lines) if pred(line)]
    assert len(hits) == 1, f"{tag}: {len(hits)} hits"
    return hits[0]


def find_next(lines, start, pred, tag):
    hits = [i for i in range(start, len(lines)) if pred(lines[i])]
    assert hits, f"{tag}: no hit after {start}"
    return hits[0]


def save(scratch, rel, lines):
    fp = os.path.join(scratch, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, "w").write("\n".join(lines) + "\n")


# ---- reconstruct the post-0193 base (SweetHID.cpp only) ----
tmp = tempfile.mkdtemp(prefix="b0194")
save(tmp, f"{HID}/SweetHID.cpp", read(f"{BASE}/{HID}/SweetHID.cpp"))
subprocess.run(["git", "init", "-q", tmp], check=True)
subprocess.run(["git", "-C", tmp, "config", "user.email", "v@v"], check=True)
subprocess.run(["git", "-C", tmp, "config", "user.name", "v"], check=True)
subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
subprocess.run(["git", "-C", tmp, "commit", "-qm", "pre0193"], check=True)
r = subprocess.run(["git", "-C", tmp, "apply", "-p1", P193],
                   capture_output=True, text=True)
assert r.returncode == 0, f"0193 did not apply: {r.stderr}"
sh = read(f"{tmp}/{HID}/SweetHID.cpp")
post193 = list(sh)
log = []

# [1] replace the whole per-board geometry block (both arms).
i_native = find_one(sh, lambda l: 'PE_parse_boot_argn("sweetfb_native"' in l,
                    "[1] native arg")
i_a5 = find_next(sh, i_native,
                 lambda l: "#if defined(ARM64_BOARD_CONFIG_A5XELTE)" in l,
                 "[1] A5XELTE arm")
i_else = find_next(sh, i_a5, lambda l: l.strip() == "#else", "[1] #else")
i_end = find_next(sh, i_else, lambda l: l.strip() == "#endif", "[1] #endif")
assert i_a5 < i_else < i_end, "geometry block shape"
assert i_end - i_a5 < 20, "geometry block unexpectedly large"

new_geom = [
    "\t/*",
    "\t * 0194: BOTH ARM64_BOARD_CONFIG_PRA and ARM64_BOARD_CONFIG_A5XELTE",
    "\t * are on the PRA compile line, so THIS arm is the one that runs on",
    "\t * PRA. 0193 added fPanelW/fPanelH only to the #else arm, leaving",
    "\t * them zero here - the panel clamp then turned every real touch",
    "\t * into (-1,-1). Initialize the panel in BOTH arms.",
    "\t * PRA's panel is 1080x1920 (pra_touch.c PANEL_X_MAX/PANEL_Y_MAX",
    "\t * and the framebuffer's 1080x1920 swaps), the same geometry as the",
    "\t * working A5 board, so publish that board's real 68x121 mm.",
    "\t */",
    "\tint surfaceWmm, surfaceHmm;",
    "",
    "#if defined(ARM64_BOARD_CONFIG_A5XELTE)",
    "\tfPanelW = 1080;",
    "\tfPanelH = 1920;",
    "\tfLogicalW = 1080;",
    "\tfLogicalH = 1920;",
    "\tfOffX = fOffY = 0;",
    "\tsurfaceWmm = 68;\t/* the 1080x1920 panel's real ~68x121 mm */",
    "\tsurfaceHmm = 121;",
    "\tIOLog(\"SWEET HID: panel arm A5XELTE 1080x1920\\n\");",
    "#else",
    "\tfPanelW = 1080;\t/* the PRA panel (the framebuffer's native) */",
    "\tfPanelH = 2400;",
    "\tfLogicalW = native ? 1080 : 1125;\t/* the presented iPhone X display */",
    "\tfLogicalH = native ? 2400 : 2436;",
    "\tfOffX = (fLogicalW - fPanelW) / 2;",
    "\tfOffY = (fLogicalH - fPanelH) / 2;",
    "\tsurfaceWmm = 132;",
    "\tsurfaceHmm = 144;",
    "#endif",
]
sh[i_a5:i_end + 1] = new_geom
log.append("[1] fPanelW/fPanelH initialized in BOTH arms (A5XELTE = 1080x1920)")

# [2] one branch-aware SurfaceWidth/SurfaceHeight pair.
i_sw = find_one(sh, lambda l: 'setProperty("SurfaceWidth"' in l, "[2] SurfaceWidth")
i_h_if = find_next(sh, i_sw,
                   lambda l: l.strip() == "#if defined(ARM64_BOARD_CONFIG_A5XELTE)",
                   "[2] height #if")
i_h_else = find_next(sh, i_h_if, lambda l: l.strip() == "#else", "[2] height #else")
i_h_end = find_next(sh, i_h_else, lambda l: l.strip() == "#endif", "[2] height #endif")
new_surface = [
    '\tsetProperty("SurfaceWidth", (unsigned long long)((unsigned)surfaceWmm << 16), 32);\t/* mm, 16.16 */',
    '\tsetProperty("SurfaceHeight", (unsigned long long)((unsigned)surfaceHmm << 16), 32);',
]
sh[i_sw:i_h_end + 1] = new_surface
log.append("[2] one branch-aware SurfaceWidth/SurfaceHeight pair (68x121 A5 arm)")

# [3] the surface marker prints the branch mm and panel.
i_mm = find_one(sh, lambda l: "8655995 >> 16" in l, "[3] surface mm args")
sh[i_mm] = "\t    surfaceWmm, surfaceHmm, fPanelW, fPanelH);"
log.append("[3] surface marker prints the real per-arm mm and panel")

# [4] structural assertions on the modified source.
src = "\n".join(sh)
assert src.count("fPanelW = 1080;") == 2, "panel init in both arms"
assert "\tfPanelH = 1920;\n\tfLogicalW = 1080;" in src, "compiled arm panel"
assert "\tfPanelH = 2400;" in src, "else arm panel"
assert "surfaceWmm = 68;" in src and "surfaceHmm = 121;" in src
assert "SWEET HID: panel arm A5XELTE 1080x1920" in src
assert "x = x < 0 ? 0 : (x >= fPanelW ? fPanelW - 1 : x);" in src
assert "y = y < 0 ? 0 : (y >= fPanelH ? fPanelH - 1 : y);" in src
assert "8655995" not in src and "9422111" not in src
log.append("[4] structural assertions PASS (both arms, clamps intact, markers)")

# ---- emit ----
d = difflib.unified_diff(post193, sh,
                         fromfile=f"a/{HID}/SweetHID.cpp",
                         tofile=f"b/{HID}/SweetHID.cpp",
                         n=3, lineterm="")

header = """pra: 0194 - the touch panel init in the COMPILED arm (the -1,-1 fix)

THE BOOTED KERNEL PROVED THE ROOT CAUSE (work/ci193/dl, T17 kernel
cc83d49c): the PRA compile line defines BOTH -DARM64_BOARD_CONFIG_PRA
and -DARM64_BOARD_CONFIG_A5XELTE (work/ci193/fail/build.log:34742), so
SweetHIDTouch::start() is compiled with the A5XELTE arm (the const pool
@0x702e720 holds 1080,1920,0,0). 0193 added fPanelW/fPanelH ONLY to the
#else arm; in the compiled arm start() never stores them (the
disassembly has no str to [x19,#0xc0]/[x19,#0xc4]) and they stay zero.
touch() then clamps with `x >= fPanelW ? fPanelW - 1 : x`; fPanelW = 0
subtracts 1 into -1, so every real coordinate became -1,-1 - exactly
ring58: "PRA touch: hid inject slot=0 down x=550 y=1911" followed by
"SWEET HID: touch 0 down at -1,-1 edge".

THIS PATCH (0194):
1. Initialize fPanelW/fPanelH in BOTH arms. The compiled A5XELTE arm is
   the PRA panel: 1080x1920 (pra_touch.c PANEL_X_MAX/PANEL_Y_MAX, and
   the framebuffer swaps 1080x1920), logical 1080x1920, zero offsets.
2. Publish the working A5 board's real 68x121 mm in that arm. 0193 made
   SurfaceWidth unconditional 8655995 (132.08 mm) from treating the
   5.2-inch diagonal as the width; the #else arm keeps 132x144 mm.
3. One-time marker "SWEET HID: panel arm" in the compiled arm so a
   silently skipped 0194 fails the CI strings guard.

The falsifier (next pratouchreset=1 boot): SWEET HID touch lines carry
the real injected coordinates (e.g. 550,1911) instead of -1,-1, and the
UI reacts. Still -1,-1 = the compiled arm differs from this source;
real coords but no UI = the next rung is userland routing.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(list(d)) + "\n")
print(f"[emit] wrote {OUT}")

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0194")
save(scratch, f"{HID}/SweetHID.cpp", post193)  # the post-0193 base
subprocess.run(["git", "init", "-q", scratch], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.email", "v@v"], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.name", "v"], check=True)
subprocess.run(["git", "-C", scratch, "add", "-A"], check=True)
subprocess.run(["git", "-C", scratch, "commit", "-qm", "post0193"], check=True)

r = subprocess.run(["git", "-C", scratch, "apply", "--check", "-p1", OUT],
                   capture_output=True, text=True)
print(f"[verify] git apply --check rc={r.returncode}")
assert r.returncode == 0, r.stderr
r = subprocess.run(["patch", "--fuzz=0", "--dry-run", "-p1", "-d", scratch,
                    "-i", OUT], capture_output=True, text=True)
print(f"[verify] GNU patch --fuzz=0 --dry-run rc={r.returncode}")
assert r.returncode == 0, r.stdout + r.stderr
r = subprocess.run(["git", "-C", scratch, "apply", "-p1", OUT],
                   capture_output=True, text=True)
print(f"[verify] git apply rc={r.returncode}")
assert r.returncode == 0, r.stderr
applied = read(f"{scratch}/{HID}/SweetHID.cpp")
assert applied == sh, "applied != expected"
print("[verify] SweetHID.cpp: applied == expected")
print("[verify] structural assertions PASS (panel both arms, real mm, markers)")
print("[done] VERIFY PASS: 0194 applies to post-0193 SweetHID.cpp")
for line in log:
    print("  " + line)

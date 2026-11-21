#!/usr/bin/env python3
"""gen0193.py - build xnu/patches/0193-pra-touch-surface-geometry.patch.

Base: work/ci193/pre0193/xnu = the post-0192 SweetHID.cpp.
0193 touches iokit/Kernel/arm/hid/SweetHID.cpp only.

DONOR PROOF (herolte-ref, research/herolte-ref): the S7 (HEROLTE) board
reaches the iOS home screen with WORKING touch on the SAME SweetHID
delivery path (sweet_hid_touch -> SweetHIDTouch::touch -> dispatchEvent
-> the shared queue). Its patch 0211 differs from PRA in two ways:
  1. touch() clamps the finger coordinates to the REAL panel
     (fPanelW/fPanelH = the IC's native resolution) and normalizes
     against the logical display; PRA clamps x to 1079 and y to
     fLogicalH (the 1125x2436 logical display, NOT the 1080x2400
     panel) - so a finger in the bottom 36 logical rows or past the
     panel edge is mis-normalized.
  2. it publishes the REAL physical surface (64x113 mm for the S7's
     5.1-inch panel); PRA publishes the iPhone X's 68x151 mm (the
     #else branch). The framebuffer's own constants (SWEET_FB_DOT_PITCH
     = 424 ppi, 1080 px across 5.2 in) give the PRA's REAL panel:
     width 132.1 mm, height 143.8 mm (python3: 5.2*25.4 and
     2400/424*25.4). backboardd/UIKit normalizes the absolute digitizer
     against the published mm - a 132x144 mm touch surface claimed as
     68x151 mm maps every touch ~2x off in x and in a wrong aspect
     ratio, which can push the normalized points off the display or
     break the gesture recognizers.

THIS PATCH (0193):
1. SweetHIDTouch::start: fPanelW=1080 fPanelH=2400 (the PRA panel),
   fLogicalW/fLogicalH unchanged (the 1125x2436 presented display),
   fOffX/fOffY = (logical - panel)/2.
2. SweetHIDTouch::touch: clamp x to fPanelW-1 and y to fPanelH-1
   (the real panel), keep the fOffX/fOffY normalization.
3. Publish the REAL PRA physical surface: SurfaceWidth = 132 mm
   (5.2 in x 25.4), SurfaceHeight = 144 mm (2400/424*25.4), in 16.16
   fixed - matching what the framebuffer actually renders.

Marker asserted in CI (direct yml commit): 'SWEET HID: surface'.
"""
import difflib
import os
import shutil
import subprocess
import tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci193/pre0193/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0193-pra-touch-surface-geometry.patch"
HID = "iokit/Kernel/arm/hid"


def read(path):
    return open(path, encoding="utf-8").read().splitlines()


def find_one(lines, pred, tag):
    hits = [i for i, line in enumerate(lines) if pred(line)]
    assert len(hits) == 1, f"{tag}: {len(hits)} hits"
    return hits[0]


def save(scratch, rel, lines):
    fp = os.path.join(scratch, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, "w").write("\n".join(lines) + "\n")


sh = read(f"{BASE}/{HID}/SweetHID.cpp")
log = []

# [1] the start(): add fPanelW/fPanelH and use them. The PRA branch is
# the #else (native ? 1080 : 1125 / native ? 2400 : 2436).
# The PRA block:
#   fLogicalW = native ? 1080 : 1125;
#   fLogicalH = native ? 2400 : 2436;
#   fOffX = (fLogicalW - 1080) / 2;
#   fOffY = (fLogicalH - 2400) / 2;
i_w = find_one(sh, lambda line: "fLogicalW = native ? 1080 : 1125;" in line, "[1] fLogicalW")
i_h = find_one(sh, lambda line: "fLogicalH = native ? 2400 : 2436;" in line, "[1] fLogicalH")
assert i_h == i_w + 1, "w/h adjacent"
i_ox = find_one(sh, lambda line: "fOffX = (fLogicalW - 1080) / 2;" in line, "[1] fOffX")
i_oy = find_one(sh, lambda line: "fOffY = (fLogicalH - 2400) / 2;" in line, "[1] fOffY")
assert i_oy == i_ox + 1, "ox/oy adjacent"
# Replace the whole block with the fPanel form (herolte's pattern).
new_geom = [
    "\tfPanelW = 1080;\t/* the PRA panel (the framebuffer's native) */",
    "\tfPanelH = 2400;",
    "\tfLogicalW = native ? 1080 : 1125;\t/* the presented iPhone X display */",
    "\tfLogicalH = native ? 2400 : 2436;",
    "\tfOffX = (fLogicalW - fPanelW) / 2;",
    "\tfOffY = (fLogicalH - fPanelH) / 2;",
]
sh[i_w:i_oy + 1] = new_geom
log.append("[1] fPanelW/fPanelH + the herolte-style offsets in start()")

# [2] the member declaration: add fPanelW/fPanelH.
i_mem = find_one(sh, lambda line: "int fLogicalW, fLogicalH, fOffX, fOffY;" in line, "[2] members")
sh[i_mem] = "\tint fLogicalW, fLogicalH, fOffX, fOffY, fPanelW, fPanelH;"
log.append("[2] fPanelW/fPanelH members")

# [3] the touch() clamps -> the real panel.
i_x = find_one(sh, lambda line: "x = x < 0 ? 0 : (x > 1079 ? 1079 : x);" in line, "[3] x clamp")
i_y = find_one(sh, lambda line: "y = y < 0 ? 0 : (y >= fLogicalH ? fLogicalH - 1 : y);" in line, "[3] y clamp")
assert i_y == i_x + 1, "clamps adjacent"
sh[i_x] = "\tx = x < 0 ? 0 : (x >= fPanelW ? fPanelW - 1 : x);"
sh[i_y] = "\ty = y < 0 ? 0 : (y >= fPanelH ? fPanelH - 1 : y);"
log.append("[3] touch() clamps to the real panel")

# [4] the edge clamp -> the real panel.
i_edge = find_one(sh, lambda line: "y < SWEET_TOUCH_EDGE_PX || y > fLogicalH - 1 - SWEET_TOUCH_EDGE_PX;" in line,
                  "[4] edge clamp")
# the two lines:
# 		fEdge[finger] = x < SWEET_TOUCH_EDGE_PX || x > 1079 - SWEET_TOUCH_EDGE_PX ||
# 		    y < SWEET_TOUCH_EDGE_PX || y > fLogicalH - 1 - SWEET_TOUCH_EDGE_PX;
i_x2 = find_one(sh, lambda line: "x > 1079 - SWEET_TOUCH_EDGE_PX ||" in line, "[4] edge x")
sh[i_x2] = "\t\tfEdge[finger] = x < SWEET_TOUCH_EDGE_PX || x > fPanelW - 1 - SWEET_TOUCH_EDGE_PX ||"
sh[i_edge] = "\t\t    y < SWEET_TOUCH_EDGE_PX || y > fPanelH - 1 - SWEET_TOUCH_EDGE_PX;"
log.append("[4] the edge test uses the real panel")

# [5] the published surface -> the REAL PRA physical mm (16.16 fixed).
# width: 5.2 in x 25.4 = 132.08 mm; height: 2400 / 424 x 25.4 = 143.77 mm.
SW_W = int(round(132.08 * 65536))
SW_H = int(round(143.77 * 65536))
i_surf = find_one(sh, lambda line: 'setProperty("SurfaceWidth", (unsigned long long)(68 << 16), 32);' in line,
                  "[5] SurfaceWidth")
sh[i_surf] = f'\tsetProperty("SurfaceWidth", (unsigned long long)({SW_W}ull), 32);\t/* mm, 16.16 - the PRA panel: 5.2 in x 25.4 */'
i_sh = find_one(sh, lambda line: 'setProperty("SurfaceHeight", (unsigned long long)(151 << 16), 32);' in line,
                "[5] SurfaceHeight")
sh[i_sh] = f'\tsetProperty("SurfaceHeight", (unsigned long long)({SW_H}ull), 32);\t/* mm, 16.16 - 2400 px / 424 ppi x 25.4 */'
log.append(f"[5] SurfaceWidth={SW_W} SurfaceHeight={SW_H} (the real 132x144 mm)")

# [6] the one-time marker line (the CI strings guard): the real panel
# geometry, printed once from start() - INSERTED before the existing
# "touch registered" line (keeps registerService/return intact).
i_reg = find_one(sh, lambda line: 'IOLog("SWEET HID: touch registered\\n");' in line,
                 "[6] touch registered")
sh[i_reg:i_reg] = [
    f'\tIOLog("SWEET HID: surface %ux%u mm panel %ux%u\\n",',
    f'\t    {SW_W} >> 16, {SW_H} >> 16, fPanelW, fPanelH);',
]
log.append("[6] one-time surface marker line (the CI strings guard)")

d = difflib.unified_diff(read(f"{BASE}/{HID}/SweetHID.cpp"), sh,
                         fromfile="a/iokit/Kernel/arm/hid/SweetHID.cpp",
                         tofile="b/iokit/Kernel/arm/hid/SweetHID.cpp",
                         n=3, lineterm="")

header = f"""pra: 0193 - the PRA touch SURFACE geometry (the real panel + the real mm)

DONOR PROOF (research/herolte-ref): the S7 (HEROLTE) board reaches the
iOS home screen with WORKING touch on the SAME SweetHID delivery path.
Its 0211 patch differs from PRA in two ways - both are the likely PRA
touch-death root cause:

1. CLAMP: herolte clamps the finger to the REAL panel (fPanelW/fPanelH)
   then normalizes against the logical display; PRA clamps x to 1079 and
   y to fLogicalH (the 1125x2436 presented display) - a finger in the
   bottom 36 logical rows or off the 1080x2400 panel edge is
   mis-normalized and can map off the rendered surface.

2. SURFACE: herolte publishes its REAL physical mm (64x113 for the S7);
   PRA publishes the iPhone X's 68x151 (the #else branch). The PRA
   framebuffer's own constants (SWEET_FB_DOT_PITCH = 424 ppi, 1080 px
   across 5.2 in) give the REAL panel: width 132.08 mm (5.2 x 25.4),
   height 143.77 mm (2400 / 424 x 25.4). backboardd/UIKit normalizes
   the absolute digitizer against the published mm surface - claiming a
   132x144 mm panel as 68x151 mm maps every touch ~2x off in x and in a
   wrong aspect ratio, which can break the gesture recognizers and the
   touch-to-display correlation (the T14-T16 "drained but dead" rung).

THIS PATCH (0193):
1. start(): fPanelW=1080 fPanelH=2400, the herolte offsets
   ((logical - panel) / 2), the logical display unchanged (1125x2436).
2. touch(): clamp to fPanelW-1/fPanelH-1; the edge test to the panel.
3. SurfaceWidth = {SW_W} (132.08 mm), SurfaceHeight = {SW_H}
   (143.77 mm) in 16.16 fixed - the REAL PRA panel, matching what the
   framebuffer renders.

The falsifier (next pratouchreset=1 boot): touch works (the UI reacts)
= the surface/correlation rung was the blocker; still dead = the
normalization was not (or not the only) cause - the delivery rung is
then fully proven and the AKS/backboardd-userland path is next.

Marker asserted in CI (direct yml commit): 'SWEET HID: surface'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(list(d)) + "\n")
print(f"[emit] wrote {OUT}")
for line in log:
    print("  " + line)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0193")
save(scratch, f"{HID}/SweetHID.cpp", read(f"{BASE}/{HID}/SweetHID.cpp"))
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
got = open(os.path.join(scratch, f"{HID}/SweetHID.cpp")).read()
assert got == "\n".join(sh) + "\n", "SweetHID.cpp mismatch"
print("[verify] SweetHID.cpp: applied == expected")

# structural assertions
scan = "\n".join(sh)
assert scan.count("fPanelW") >= 5, "fPanelW wired (decl + start + clamp x2 + edge)"
assert scan.count("fPanelH") >= 5, "fPanelH wired"
assert "x >= fPanelW ? fPanelW - 1 : x" in scan, "x clamp to panel"
assert "y >= fPanelH ? fPanelH - 1 : y" in scan, "y clamp to panel"
assert str(SW_W) in scan and str(SW_H) in scan, "the real mm constants"
assert "(68 << 16)" not in scan, "the iPhone X width gone"
assert "(151 << 16)" not in scan, "the iPhone X height gone"
assert scan.count("{") == scan.count("}"), "brace balance"
print("[verify] structural assertions PASS (panel clamp, real mm, braces)")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0193 applies to the post-0192 SweetHID.cpp")
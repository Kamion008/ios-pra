# Evidence 1 - the T17 ring pair (work/ring58-own.txt:2501-2502)

```
PRA touch: hid inject slot=0 down x=550 y=1911
SWEET HID: touch 0 down at -1,-1 edge
```

The caller logged the real IC coordinates immediately before the callee
logged -1,-1. (All 44 `SWEET HID: touch` lines in ring58 carry -1,-1;
the one `hid inject` line is the one-shot marker from pra_touch_inject.)

# Evidence 2 - BOTH board macros are defined (work/ci193/fail/build.log:34742)

```
clang++ ... -DARM64_BOARD_CONFIG_PRA -DARM64_BOARD_CONFIG_A5XELTE ...
  /Users/runner/.../dxb/xnu/iokit/Kernel/arm/hid/SweetHID.cpp
```

So `#if defined(ARM64_BOARD_CONFIG_A5XELTE)` selects the A5XELTE arm of
SweetHIDTouch::start() in the PRA kernel.

# Evidence 3 - the T17 kernel cc83d49c disassembly (work/ci193/dl)

`llvm-nm` still names the functions:
```
fffffff007a5c280 S __ZN13SweetHIDTouch5startEP9IOService
fffffff007a5c3a0 S __ZN13SweetHIDTouch5touchEibii
fffffff007a5c9e0 S _sweet_hid_touch
```

start() loads the A5XELTE geometry constants (1080, 1920, 0, 0) from the
const pool @0x702e720 and stores them once:
```
fffffff007a5c2e4: ldr  q0, [x8, #0x720]
fffffff007a5c2f0: str  q0, [x19, #0xb0]      ; fLogicalW/H, fOffX/Y
```
The SurfaceHeight property in this arm is 0x790000:
```
fffffff007a5c328: mov  w2, #0x790000          ; 121 << 16 (the A5 arm)
```
There is NO store to [x19,#0xc0] (fPanelW) or [x19,#0xc4] (fPanelH)
anywhere in start() - 0193 added those assignments only to the #else arm.

touch() reads those slots for the clamp:
```
fffffff007a5c408: ldr  w8, [x19, #0xc0]       ; fPanelW
fffffff007a5c40c: sub  w9, w8, #1
fffffff007a5c410: cmp  w8, w23                ; panelW vs x
fffffff007a5c414: csel w23, w23, w9, gt
fffffff007a5c420: ldr  w8, [x19, #0xc4]       ; fPanelH
fffffff007a5c424: sub  w9, w8, #1
fffffff007a5c428: cmp  w8, w20
fffffff007a5c42c: csel w20, w20, w9, gt
```
With fPanelW/H = 0 every coordinate selects `0 - 1`:
```
$ python3 -c 'print("0 - 1 =", 0-1)'
0 - 1 = -1
```
That is the exact -1,-1 in Evidence 1. The real x (550) and y (1911)
never enter the printed/queued values.

# Evidence 4 - 0193's published mm (the compiled arm)

At T17 the compiled A5XELTE arm publishes SurfaceWidth = 8655995
(132.08 mm, from 0193) and SurfaceHeight = 0x790000 (121 mm, the A5
arm) - an inconsistent pair. The 132.08 came from treating the 5.2-inch
diagonal as the width:
```
$ python3 -c 'print(5.2*25.4)'
132.07999999999998
$ python3 -c 'print(round(1080/424*25.4,2))'
64.7
```
The working A5 board (same 1080x1920 panel) publishes 68x121 mm.

# Evidence 5 - the patch (xnu/patches/0194-pra-touch-panel-init.patch)

```diff
 #if defined(ARM64_BOARD_CONFIG_A5XELTE)
+	fPanelW = 1080;
+	fPanelH = 1920;
 	fLogicalW = 1080;
 	fLogicalH = 1920;
 	fOffX = fOffY = 0;
+	surfaceWmm = 68;	/* the 1080x1920 panel's real ~68x121 mm */
+	surfaceHmm = 121;
+	IOLog("SWEET HID: panel arm A5XELTE 1080x1920\n");
 #else
 	fPanelW = 1080;
 	fPanelH = 2400;
 	...
+	surfaceWmm = 132;
+	surfaceHmm = 144;
 #endif
 	setProperty("DisplayIntegrated", kOSBooleanTrue);
-	setProperty("SurfaceWidth", (unsigned long long)(8655995ull), 32);
-#if defined(ARM64_BOARD_CONFIG_A5XELTE)
-	setProperty("SurfaceHeight", (unsigned long long)(121 << 16), 32);
-#else
-	setProperty("SurfaceHeight", (unsigned long long)(9422111ull), 32);
-#endif
+	setProperty("SurfaceWidth", (unsigned long long)((unsigned)surfaceWmm << 16), 32);
+	setProperty("SurfaceHeight", (unsigned long long)((unsigned)surfaceHmm << 16), 32);
 	...
 	IOLog("SWEET HID: surface %ux%u mm panel %ux%u\n",
-	    8655995 >> 16, 9422111 >> 16, fPanelW, fPanelH);
+	    surfaceWmm, surfaceHmm, fPanelW, fPanelH);
```

# Evidence 6 - the generator verify (work/gen0194.py run)

```
[emit] wrote .../xnu/patches/0194-pra-touch-panel-init.patch
[verify] git apply --check rc=0
[verify] GNU patch --fuzz=0 --dry-run rc=0
[verify] git apply rc=0
[verify] SweetHID.cpp: applied == expected
[verify] structural assertions PASS (panel both arms, real mm, markers)
[done] VERIFY PASS: 0194 applies to post-0193 SweetHID.cpp
  [1] fPanelW/fPanelH initialized in BOTH arms (A5XELTE = 1080x1920)
  [2] one branch-aware SurfaceWidth/SurfaceHeight pair (68x121 A5 arm)
  [3] surface marker prints the real per-arm mm and panel
  [4] structural assertions PASS (both arms, clamps intact, markers)
```

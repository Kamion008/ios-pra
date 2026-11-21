# Evidence 1 - boot T16, the delivery fully proven (work/ring57.raw sha 3a4e5698)
```
SWEET HID: SweetHIDTouch open by IOHIDEventServiceUserClient -> 1
SWEET HID: queue mapped by SweetHIDTouch
SWEET HID: queue notify armed by SweetHIDTouch
SWEET HID: SweetHIDButtons open by IOHIDEventServiceUserClient -> 1
SWEET HID: queue mapped by SweetHIDButtons
SWEET HID: queue notify armed by SweetHIDButtons
SWEET HID: event size=236 sender=0x100000126
SWEET HID: queue stats enq=0 drop=0 type=0 head=0 tail=0
SWEET HID: queue stats enq=68 drop=0 type=11 head=16320 tail=16320
SWEET HID: queue stats enq=71 drop=0 type=11 head=720 tail=720
SWEET HID: queue stats enq=107 drop=0 type=11 head=9360 tail=9360
... (22 stats lines) ...
SWEET HID: queue stats enq=641 drop=0 type=11 head=9120 tail=9120
```
The 0192 telemetry: notify armed for BOTH services; every event
size=236 B, senderID=0x100000126 (nonzero); enq rises 0->641 with
drop=0 throughout; head == tail at 22/22 samples (100%) - the queue is
EMPTY at every 1 s snapshot. Drain proof: 641 x 236 = 147.7 KiB through
the 16 KiB queue = 9.2x overflow, zero drops - userland dequeues every
event. The enq deltas (68, 63, 59, 75, 73, 56...) with head resetting to
~0 between bursts show the fill->drain cycle; max head watermark 16,320
of 16,384. Input re-confirmed: reports 1->454, last burst +272 in 10 s
= 27.2 reports/s. SpringBoard AKS in the touch window: 8 one-shot calls
(sel 8 -> 0xe00002c7 x2 = the default-case Unsupported) - the SAME
triad pattern as T15's pre-boot churn, background. SpringBoard does ZERO
SWEET FB framebuffer calls.

# Evidence 2 - the donor proof (research/herolte-ref)
The S7 (HEROLTE) reaches the iOS home screen with WORKING touch on the
SAME SweetHID delivery path. HEROLTE_PROGRESS.md:
- "🖐 Táctil funcionando (0216...)": sec_ts in app mode (0x20, id
  ac a5 52), touches reach iOS, coords 0..4095 confirmed.
- "🏠 Pantalla de inicio de iOS (2026-10-23): ... pantalla de inicio y
  Centro de control con el táctil."
- "Ajustes > Información abre (iPhone X, iOS 16.7.16, 21 GB)" - the
  S7 presents the iPhone X identity (1125x2436) and touch works.

Patch 0211 (herolte's touch + geometry), the SweetHIDTouch differences:
```c
#if defined(ARM64_BOARD_CONFIG_HEROLTE)
	fPanelW = 1440;          /* the S7's REAL panel */
	fPanelH = 2560;
	fLogicalW = native ? 1440 : 1125;
	fLogicalH = native ? 2560 : 2436;
#else  /* PRA's current code, the #else branch */
	fLogicalW = native ? 1080 : 1125;
	fLogicalH = native ? 2400 : 2436;
	fOffX = (fLogicalW - 1080) / 2;
	fOffY = (fLogicalH - 2400) / 2;
#endif
	fOffX = (fLogicalW - fPanelW) / 2;   /* herolte */
	fOffY = (fLogicalH - fPanelH) / 2;
	setProperty("SurfaceWidth", (unsigned long long)(64 << 16), 32);  /* the S7's REAL mm */
	setProperty("SurfaceHeight", (unsigned long long)(113 << 16), 32);
	/* touch() clamps to the PANEL: x >= fPanelW ? fPanelW-1 : x */
	/*                    y >= fPanelH ? fPanelH-1 : y */
```

# Evidence 3 - the working-board surface common thread
| board | panel | logical | offsets | Surface mm |
|---|---|---|---|---|
| A5 (working, 0123) | 1080x1920 | 1080x1920 | 0/0 | 68x121 (real) |
| HEROLTE (working, 0211) | 1440x2560 | 1125x2436 | (1125-1440)/2, (2436-2560)/2 | 64x113 (real) |
| PRA (dead, current) | 1080x2400 | 1125x2436 | 22/18 | 68x151 (the iPhone X's) |
Both working boards publish SurfaceHeight = their REAL physical panel
height; PRA publishes the iPhone X's 151 mm for a real ~144 mm panel.
The PRA framebuffer's own constants (SweetFramebuffer.cpp:
SWEET_FB_DOT_PITCH = 424 ppi, 1080 px across 5.2 in):
- width = 5.2 x 25.4 = 132.08 mm
- height = 2400 / 424 x 25.4 = 143.77 mm
(python3: 5.2*25.4 = 132.08; 2400/424*25.4 = 143.77)

# Evidence 4 - the patch (xnu/patches/0193-pra-touch-surface-geometry.patch)
```diff
--- a/iokit/Kernel/arm/hid/SweetHID.cpp
@@ -374,7 +374,7 @@
-	int fLogicalW, fLogicalH, fOffX, fOffY;
+	int fLogicalW, fLogicalH, fOffX, fOffY, fPanelW, fPanelH;
@@ -446,21 +446,25 @@
-	fLogicalW = native ? 1080 : 1125;
+	fPanelW = 1080;	/* the PRA panel (the framebuffer's native) */
+	fPanelH = 2400;
+	fLogicalW = native ? 1080 : 1125;	/* the presented iPhone X display */
 	fLogicalH = native ? 2400 : 2436;
-	fOffX = (fLogicalW - 1080) / 2;
-	fOffY = (fLogicalH - 2400) / 2;
+	fOffX = (fLogicalW - fPanelW) / 2;
+	fOffY = (fLogicalH - fPanelH) / 2;
-	setProperty("SurfaceWidth", (unsigned long long)(68 << 16), 32);
+	setProperty("SurfaceWidth", (unsigned long long)(8655995ull), 32);
-	setProperty("SurfaceHeight", (unsigned long long)(151 << 16), 32);
+	setProperty("SurfaceHeight", (unsigned long long)(9422111ull), 32);
+	IOLog("SWEET HID: surface %ux%u mm panel %ux%u\n",
+	    8655995 >> 16, 9422111 >> 16, fPanelW, fPanelH);
@@ -475,8 +479,8 @@
-	x = x < 0 ? 0 : (x > 1079 ? 1079 : x);
-	y = y < 0 ? 0 : (y >= fLogicalH ? fLogicalH - 1 : y);
+	x = x < 0 ? 0 : (x >= fPanelW ? fPanelW - 1 : x);
+	y = y < 0 ? 0 : (y >= fPanelH ? fPanelH - 1 : y);
@@ -489,8 +493,8 @@
-		fEdge[finger] = x < SWEET_TOUCH_EDGE_PX || x > 1079 - SWEET_TOUCH_EDGE_PX ||
-		    y < SWEET_TOUCH_EDGE_PX || y > fLogicalH - 1 - SWEET_TOUCH_EDGE_PX;
+		fEdge[finger] = x < SWEET_TOUCH_EDGE_PX || x > fPanelW - 1 - SWEET_TOUCH_EDGE_PX ||
+		    y < SWEET_TOUCH_EDGE_PX || y > fPanelH - 1 - SWEET_TOUCH_EDGE_PX;
```
The mm constants: 8655995 = 132.08 x 65536 (16.16 fixed), 9422111 =
143.77 x 65536 (python3-verified).

# Evidence 5 - the generator verify (work/gen0193.py run)
```
[emit] wrote .../xnu/patches/0193-pra-touch-surface-geometry.patch
  [1] fPanelW/fPanelH + the herolte-style offsets in start()
  [2] fPanelW/fPanelH members
  [3] touch() clamps to the real panel
  [4] the edge test uses the real panel
  [5] SurfaceWidth=8655995 SurfaceHeight=9422111 (the real 132x144 mm)
  [6] one-time surface marker line (the CI strings guard)
[verify] git apply --check rc=0
[verify] GNU patch --fuzz=0 --dry-run rc=0
[verify] git apply rc=0
[verify] SweetHID.cpp: applied == expected
[verify] structural assertions PASS (panel clamp, real mm, braces)
[done] VERIFY PASS: 0193 applies to the post-0192 SweetHID.cpp
```
The base: work/ci193/pre0193 = work/ci192/pre0192 + the 0192 patch
applied cleanly.
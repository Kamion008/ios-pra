# CLAIM: 0196 (the synthetic bottom-edge unlock swipe)

Author: Buffy (Freebuff session 2026-11-22). The patch is a unified diff
against the exact post-0195 tree: `work/ci193/pre0193` + 0193 + 0194 + 0195
(the reconstruction gen0195.py used). Verified by GNU
`patch -p1 --fuzz=0 --dry-run` (rc=0), `git apply` (rc=0) and `cmp` against
the edited file (`cmp rc=0`; durable copies at
`work/0196/SweetHID-pre0196.cpp` / `work/0196/SweetHID-post0196.cpp`).
`git apply --check` is recorded but is not proof (AGENTS.md: it
skip-detects already-applied patches at rc=0). The patch adds 84 lines in
4 hunks, deletes 0 (hunk adds 15+5+19+45 = 84, recounted with awk). Base evidence: T19/ring61
(claim-0195 K7-K11), the observation history below, and the donor compare.

K1 (VERIFIED): THE RECORDED PRA TOUCH TESTS WERE ON THE LOCK SCREEN, AND A
TAP THERE PROVES NOTHING. claim-0195.md:124-126, quoted: "every PRA touch
test so far (T13-T19) was observed on the LOCK SCREEN ... An inert lock
screen with a working delivery path is not excluded." HANDOFF_2026-11-21.md:171,
quoted: "many taps/swipes over the run; the iOS UI (lock screen) showed NO
reaction at all." On an iOS 16 lock screen a tap on an already-lit screen
leaves no lasting visible change; the decisive, persistent reaction is the
bottom-edge swipe up (unlock). Which gestures the user tried is not
recorded, so 0196 injects the one gesture whose success is unambiguous.
The only synthetic KEY injection that has run on PRA is `sweethidtest`,
which presses Menu/Home only (post-0195 SweetHID.cpp:430-431:
`self->key(kHIDUsage_Csmr_Menu, press);`), and an iPhone X lock screen
has no home button to press; `sweet_hid_key()`
can emit power/volume/home, but its caller never runs on this eMMC phone
(quoted below). The only synthetic TOUCH is 0195's one-shot out-of-bounds
clamp test, fired at queue-map time, before the lock screen exists.

K2 (VERIFIED, source-level): THE SWIPE USES THE PROVEN PATH AND THE REAL
EDGE BAND. The swipe calls `touch()`, the same function pra_touch's finger
path calls, so the 0194 clamp and the edge latch apply unchanged.
Post-0195 `touch()` (`work/0196/SweetHID-pre0196.cpp:516-521`), quoted
with the guard that makes the latch hold for the whole contact:
```
	if (!was && down) {
		fEdge[finger] = x < SWEET_TOUCH_EDGE_PX || x > fPanelW - 1 - SWEET_TOUCH_EDGE_PX ||
		    y < SWEET_TOUCH_EDGE_PX || y > fPanelH - 1 - SWEET_TOUCH_EDGE_PX;
	}
```
and the same function's child mask (lines 542, 557, 560):
```
		UInt32 mask = fEdge[i] ? kIOHIDDigitizerEventFromEdgeTip : 0;
		child->setIntegerValue(kIOHIDEventFieldDigitizerEventMask, mask);
		cmask |= mask;
```
so the flag is on every finger child and on the collection itself for the
whole contact (latched at down, never cleared before release). The swipe's
down is `self->touch(0, true, SWEET_SWIPE_X, SWEET_SWIPE_Y0)` (y0=1914):
```
$ python3 -c 'print(1920 - 1 - 48, 1914 > 1920 - 1 - 48, 1919 - 1914)'
1871 True 5
```
The clamp then normalizes panel pixels to the presented 1125x2436
logical display (post-0195 touch()):
```
/* Panel pixels -> the presented 1125x2436 display (SweetFramebuffer.cpp). */
IOFixed nx = (IOFixed)(((int64_t)(x + fOffX) << 16) / fLogicalW);
IOFixed ny = (IOFixed)(((int64_t)(y + fOffY) << 16) / fLogicalH);
```
so the swipe runs at logical x 562.5/1125 (centre), down y 2428/2436
(8 px from the bottom, the home-indicator band) and release y 906/2436:
```
$ python3 -c 'print(540*1125/1080, 1914*2436/1920, 714*2436/1920)'
562.5 2428.3875 905.925
```
fPanelH=1920 is in the compiled arm: 0194 sets `fPanelW = 1080;
fPanelH = 1920;` (xnu/patches/0194-pra-touch-panel-init.patch:48-49), and
the runtime proof is T19's own clamp line (`selftest 2000,3000 ->
1079,1919`) on 1080x1920 presents.

K3 (VERIFIED, source-level): THE GESTURE SHAPE, SCHEDULE AND TIMER. Down at
(540,1914), eight moves 150 px apart, release at (540,714):
```
$ python3 -c 'print([1914 - 150*k for k in range(9)], 1914-714)'
[1914, 1764, 1614, 1464, 1314, 1164, 1014, 864, 714] 1200
$ python3 -c 'print((1+8)*20, [420+120*k for k in range(3)])'
180 [420, 540, 660]
```
Ten touch() calls, nine 20 ms intervals = a 180 ms, 1200 px flick. Three
runs start `pratouchswipe=N` seconds after the touch service starts
(planned N=420), re-armed 120 s after each gesture: nominal 420/540/660 s,
real 540.18/660.36 s (the re-arm lands after the 180 ms gesture). The
last run needs ~11 min of uptime; T19's ring has 7 sampler markers
(samples 0-6), so T20 must stay booted for at least 12 min to see it. All timer state is
explicitly initialized before arming (`fSwipe = NULL; fSwipeRuns = 0;
fSwipeStep = 0; fSwipeSecs = 0;`), so the first fire always takes the
"start" branch (the round-1 REFUTED finding, fixed). Re-arming from inside
the action copies the existing button timer, which does exactly that
(post-0195 SweetHID.cpp:432 `sender->setTimeoutMS(press ? 100 :
self->fTestSecs * 1000);`); `IOTimerEventSource.h` is already included and
`_hidWorkLoop` is the same member that compiled class uses.
`PE_parse_boot_argn` is already called in this unit (lines 395, 445, 446).

K4 (INFERRED, positive only): THE UI-REACTION SIGNAL. If SpringBoard
processes the gesture, the lock screen unlocks and the UI re-renders. The
measurable signals are (a) new `SWEET FB: swap` lines - but 0046 caps that
log at 16 entries and only prints draws with a non-null surface
(`if (sweet_fb_swaps_logged < 16)`), and ring61's printed counter already
reached 13 (lines 1656, 1677, 1694, 2535, 2799, 2800, 2807, 2917, 2924 of
a 3,703-line ring print only 9 of those draws), so at most 3 more lines
can ever appear; (b) SpringBoard's AKS unlock
selectors sel 9/12 (the class named in the T4 decode, work/boots.md:44:
"the 0179 follow-up fix = narrow the gate to sel 9/12 (the real unlocks)").
Ring61's AKS census (regex `sel (9|12)( |$)` over 966 `SWEET AKS:` lines,
format `SWEET AKS: SpringBoard sel 0 arg0 ...`) is 0 for sel 9/12;
SpringBoard itself made 124 calls, contextstored 186. The USER reports (2026-11-22) that the lock screen has never drawn more
than one frame: a static, non-animating lock screen is expected to add no
swap lines at all, so swap-line absence is NOT evidence the swipe failed.
The decisive signals are therefore AKS sel 9/12 and the screen visibly
changing on return, with swap lines only a bonus. This is a
no-passcode device (tools/mkiosroot.sh:225: "# System keybag for the
built-in AppleKeyStore (no passcode)."), so a successful swipe cannot land
on a passcode keypad: it is accepted (new swaps and/or AKS) or not.

K5 (UNKNOWN): whether backboardd dispatches the drained digitizer events
to SpringBoard at all. A negative swipe result is ambiguous between a
rejected gesture and a dispatch drop (the 16 KiB queue itself is proven:
drop=0, head==tail); the follow-up probes decide it. The iPhone X userland
stays unmodified, per the session direction.

FALSIFIER: `SWEET HID: swipe 1 start (interval 420 s) at 540,1914`, all
eight `move k/8` lines, then `swipe 1 release at 540,714`, followed by a
burst of new `SWEET FB: swap` lines and/or SpringBoard AKS sel 9/12 = the
UI processed the gesture (touch DONE; the earlier deadness was the lock
screen's inert tap surface). A negative does NOT by itself separate the
three live branches (gesture rejected, backboardd dispatch drop,
SpringBoard never routed it). No `SWEET HID: swipe` line at all = the
timer never fired, which is also what a failed addEventSource or an
unparsed/zero pratouchswipe looks like (the arming block logs nothing on
those failures), so T20 keeps pratouchselftest=1 as the queue-alive
control; the first swipe line carries the interval because start()'s own
IOLog precedes the pralog ring.

DONOR COMPARISON (VERIFIED): the PRA and A5XELTE
`0058-sweet-hid-event-services.patch` files are byte-identical (captured
`cmp rc=0`, both paths existence-checked), so the event-construction code
(collection + finger children, masks, normalized coordinates) is the code
that delivers working touch on the A5 board. 0193/0194 changed geometry
constants in that file and 0195 added a one-shot diagnostic; 0196 adds
only the timer and the gesture. A kernel event-layout difference is
therefore the low-probability branch.

PRIOR-ART CHECK (VERIFIED, quoted):
- HANDOFF_2026-11-20 lists the same four downstream candidates
  (HIDEventSystem loop, senderID, SpringBoard router, payload parser) and
  probes A-D; none of the four landed. 0192's size/sender telemetry was
  the last HID telemetry.
- The process sampler exists but has only ever been aimed at Setup on PRA:
  ring61 has 7 `SMP --- sample N` markers (sample 0 through 6) and 0
  `SMP Setup[` lines (Setup is not running). SpringBoard/backboardd
  sampling is untried.
- `sweetiolog` is compiled only under `#if defined(ARM64_BOARD_CONFIG_SWEET)`
  (0049-sweet-iokit-trace.patch:9); ring61 has 0 `IOK ` lines.
- `sweet_keys_init` has a call site (0060, the sweet_ufs probe), but that
  probe never attaches on this eMMC phone (0161, quoted: "never attaches
  on this eMMC phone, so sweetsample has been dead here since 0054 (0
  \"SMP\" lines in ring17 despite the default boot-arg)"), and ring61 has
  0 `SWEET KEYS` lines.
- The only prior synthetic touch is 0195's one-shot out-of-bounds clamp
  test, fired at queue-map time (before the lock screen exists).

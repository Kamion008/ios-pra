# CLAIM: 0203 (display power honesty — the wake-gate lever after ring66)

Author: session 2026-11-23 (the T23/ring66 verdict). Claim for the landed patch
`xnu/patches/0203-pra-fb-power-honesty.patch`. Base = work/0202/SweetFramebuffer-
pre0202.cpp (the post-0202 CI tree file; 0202 touches no framebuffer file).
Companion: work/evidence-0202.md (the 0202 verify, still valid for the base),
work/boots.md T23 outcome (the falsifier that authorizes 0203), the hw-* design
notes (the parallel hardware tracks).

K1 (VERIFIED, ring66 + user report): THE HOST-STATE LEVER IS FALSIFIED — the
gate is the display-power lie. T23/ring66: 0202 landed (keyvalue TouchDetectionMode
x13, digitizer update masks set once, no unsupported refusals) but backboardd
pushed ZERO host-state keys despite the new MultitouchHostStateKeys advertisement,
and touch worked exactly as before — only after a power press (user report,
2026-11-23: "the device is not woken up unless you press the power button").
26 touch transitions arrived BEFORE the first power key and were ignored; the
display was believed OFF from powerreq n=2 (line 1469) through the first key.
The T21-era tracev3 already named the mechanism: SpringBoard's winning
BKSHIDUISensorMode (score 4108) carries digitizerEnabled: NO; displayState: off
from the BLS idle-timer sleep. The kernel's `a5fb_keep_on=1` REFUSES every
display-off request (ring65/66: powerreq n=N arg=0 off=1 keep=1 applied=1), so
userland believes displayState: off while the panel stays lit — the state split
(E3, digitizer-gate-2026-11-22.md) that latches the digitizer off.

K2 (VERIFIED, source): WHAT 0203 DOES. One new AppleCLCD::notifyAll(type,
values, count) — walks every open IOMobileFramebufferUserClient under fLock and
calls notify(); notify() returns silently when the client has no function
registered for the type (fFunc[type]==0) or no port, so an unsubscribed type
costs one null check. On every APPLIED power transition (off != previous
fPowerOff, i.e. after the keep_on path — in the T23 cmdline it never swallows
because 0203's flash drops a5fb_keep_on=1): publish `DisplayPowerOff` read-back
property (kOSBoolean), log `SWEET FB: power change notified (off=N)` once per
transition, notifyAll(0..7, {off,0}, 2) for every type (bounded by
SWEET_FB_NOTIFY_TYPES=8). The vsync fan-out (type 5, 6 words) is unchanged.
The changed-vs-applied logic: `changed` is computed INSIDE the lock before the
assignment (the first draft had it after — that would have made it always false;
caught in review before the patch landed).

K3 (VERIFIED, commands): THREE-WAY VERIFY PASSED, zero skips. Leg 1: GNU patch
-p1 --fuzz=0 --dry-run + apply on the base, cmp rc=0. Leg 2: the full 194-patch
stack on pristine xnu-8796.141.3 with the stage scripts (MACHINE_CONFIG=PRA
MACOS_VERSION=13.5), git apply --check && git apply in glob order — skips: 0 —
and the resulting SweetFramebuffer.cpp byte-matches work/0202/SweetFramebuffer-
post0203.cpp (cmp rc=0); SweetHID.cpp unchanged (cmp rc=0 vs post0202). Leg 3:
already-applied discrimination git rc=1 + GNU rc=1 (both tools, AGENTS.md:44-49).
Hunk arithmetic: python3 exact recount 4 hunks +44/-0, all consistent. The patch
is index-stripped (0 diff --git/index lines). Marker: `SWEET FB: power change
notified` — contiguous literal, asserted in .github/workflows/xnu.yml.

K4 (PREDICTION, ring67 = the 0203 control boot): cmdline = T23's minus
a5fb_keep_on=1 (keys still on as control). Expect `powerreq ... off=1 keep=0
applied=1` (the falsifier for the cmdline change — keep=0 proves keep_on is
gone), `SWEET FB: display off/on`, `SWEET FB: power change notified (off=N)`,
and the A5XELTE ignored line ABSENT. Then: does the power key (first pair
+900 s) wake the UI (display back on, user-visible)? With honest power the
idle-timer sensor-mode may no longer latch — the touch gate may already move in
THIS boot news the key toggles the display. Falsifiers: keep=1 anywhere (cmdline
did not land — re-package); display stays dark after the press (wake path is
display-gated — the keyless deliverable moves to a real wake driver); SpringBoard
not returning after an off->on cycle (the 0179 fade/black path removed something
the userland needs).

K5 (THE DELIVERABLE): the KEYLESS boot — same 0203 image, cmdline WITHOUT
prapowerkey/prakeyevery AND without a5fb_keep_on=1 — must reach the lock screen
with touch working from boot (digitizerEnabled: YES at boot, no idle-timer
latch). That boot is the goal; it is recorded as the deliverable test in
boots.md and requires explicit user approval for the flash. 0203 can blank the
panel (with keep_on gone) — that is the stated cost of the test (handoff: 0203
LAST), and the recovery is the known-good T22/0202 image reflash.

K6 (SCOPE): 0203 does NOT implement a real power-button driver, a brightness
selector, or a tap-to-wake path (WakeOnTapEnabled stays unadvertised — no lie
to backboardd). It only stops the kernel from lying about display power so the
userland's sensor-mode bookkeeping has a chance to stay awake. The hw-* tracks
(GPU / 1.375 GiB RAM / 8-core cluster-1 scheduler panic) are scoped in
work/hw-gpu-status.md, work/hw-3gb-design.md, work/hw-8core-design.md and
continue in parallel.
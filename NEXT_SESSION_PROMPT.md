You are taking over the PRA Touch investigation: running the unmodified
iPhone X iOS 16.7.16 userland on a Huawei PRA-LX1 (Kirin 655/hi6250) via
an Android boot image, the shim/pra EL1 loader and a ported XNU
8796.141.3. The phone reaches the iOS lock screen; the display is live;
the kernel touch path (touch IC -> HID queue -> backboardd) is fully
proven; the UI ignores every touch. You may change the kernel only -
iPhone X userland stays unmodified.

READ FIRST, IN THIS ORDER
1. ios/ios-pra/HANDOFF_2026-11-22b.md - THE source of truth and
   self-contained: the proven/refuted lists, the T20 outcome, the T20
   confound, the three-branch blocker, and the full T21 design with code
   anchors. Read it before anything else; do not rely on older handoffs.
2. ios/ios-pra/AGENTS.md - build/flash/log mechanics, patch hygiene, the
   arithmetic rule, safety rules.
3. ios/ios-pra/work/claim-0197.md + work/evidence-0197.md - what the T20
   ring proved, refuted and left open; work/ring62-decode.md is the raw
   tabulation.
4. Context only: work/claim-0196.md, work/evidence-0196.md,
   work/0196-review.txt (the swipe patch; do NOT re-run it).

WHERE THINGS STAND
T20 decoded to decode-ladder BRANCH 2: the synthetic bottom-edge swipe was
DELIVERED and NOT VISIBLY ACCEPTED. Not a pass, not a fail, and touch does
not work. The three swipes fired exactly as designed (start 540,1914, then
move 1/8..8/8 with the 150 px ladder, release 540,714; 31 swipe lines) and
the control fired first (`selftest raw 2000,3000` -> `touch 0 down/up at
1079,1919 edge`). Delivery held: queue enq 0 -> 2 -> 12 -> 22, drop=0,
head==tail, exactly one 236 B event per touch() call. Acceptance did not
happen: SpringBoard AKS sel 9 = 0 and sel 12 = 0 (identical to the ring61
baseline) and the user reports the lock screen unchanged. SpringBoard was
alive throughout (it created five more surfaces after swipe 1).

THE CONFOUND YOU MUST NOT REPEAT: T20's cmdline carried
`pratouchswipe=420 pratouchselftest=1 pratouchdbg=1` but NOT `pratouch=1`
and NOT `pratouchreset=1`. The touch IC was therefore never brought up
(0 `PRA touch` lines vs 104 in ring61) and the user's own taps during T20
were no-ops by construction - only the synthetic swipes count. The swipe
still fired because 0196 arms its timer unconditionally in
SweetHIDTouch::start(). Every touch boot must pass `pratouch=1
pratouchreset=1`.

THE ANSWERED SIDE QUESTION: the 236 B event vs 240 B queue stride is NOT a
discrepancy - each queue entry is a 4 B header plus the event
(`DATA_QUEUE_ENTRY_HEADER_SIZE` = sizeof(IODataQueueEntry) - 4 = 4). Do
not re-open it.

THE OPEN QUESTION: three branches, unseparated - (a) the gesture is
rejected at the HID layer, (b) backboardd's HIDEventSystem drops it before
dispatch, (c) backboardd dispatches and SpringBoard never accepts it. A
negative swipe cannot tell them apart, which is why T20 is branch 2 and not
a verdict.

FIRST ACTION
Run `adb devices`. If the PRA-LX1 is in TWRP, it is where it should be -
ring62 is already banked, so nothing is at risk, but pull any newer ring
before booting (every XNU boot overwrites the ring). If it is not in TWRP,
ask the user (1) what the screen shows and (2) to return it to TWRP
without booting XNU. Do not flash or boot before T21's image exists.

T21 = THE NON-DIGITIZER CONTROL (the next boot, patch 0198)
Add ONE boot arg that fires one synthetic POWER (consumer page) key
down+up through SweetHIDButtons' own service - the queue backboardd
already maps and arms. `SweetHIDButtons::key(usage, down)` builds
`IOHIDEvent::keyboardEvent(mach_absolute_time(), kHIDPage_Consumer,
usage, down)` and dispatches it; there is no latch, no finger slot and no
PMIC dependency, and the registered instance is reachable as
`gSweetButtons` (`sweet_hid_key()` already maps index 0 to
kHIDUsage_Csmr_Power = 0x30). Copy 0196's timer pattern exactly: arm an
IOTimerEventSource in start() behind the arg, log the interval at the
first fire, run the callback on _hidWorkLoop, initialise the timer state
explicitly, and make the arming block FAIL LOUDLY on parse/addEventSource
failure (0196's silence is why "no line" was ambiguous in T20).

THE LADDER (state it as a branch, never as a pass/fail):
- Key enqueued + drained AND a visible display change: a non-digitizer HID
  event IS accepted end to end -> the defect is digitizer-specific, and
  the live branches become (a)/(b)-narrow for the digitizer.
- Key enqueued + drained and nothing visible: branch 2 again, now proven
  NON-digitizer-specific - the drop is at the queue -> dispatch boundary
  for every event type.
- Key never enqueued: a patch bug, not a finding - fix and reflash.
- `pratouch=1` present but 0 `PRA touch` lines: the IC path regressed;
  report it as a separate finding.
A positive is decisive; a negative is weaker (iOS may not map our usage
value to sleep/wake), so record it that way and consider adding a
volume-key press (visible HUD) as a hedge in the same boot.

BUNDLE IN THE SAME BOOT (no extra cost)
- `pratouch=1 pratouchreset=1 pratouchdbg=1` restored (IC live, confound
  gone), `pratouchselftest=1` kept as the queue-alive control, and NO
  `pratouchswipe`.
- The sampler aimed at SpringBoard/backboardd - this needs NO patch: the
  arg already takes a comma list and its built-in default is
  "SpringBoard,backboardd"; the PRA cmdline overrides it with
  `sweetsample=Setup`, a process that never runs, which is why no ring has
  ever carried an `SMP <name>[pid]` line. Drop or change that arg.
- Expected positive markers: `SWEET HID: key 0x30 down/up (1 clients)` and
  `SWEET HID: event size=60`; a press+release pair costs 128 B of the
  16,384 B queue. A press before the queue is mapped still logs
  `(0 clients)` - use it as the arming health check.

DECODE (greps; the ring procedure is in the handoff)
Pull the new ring from TWRP BEFORE any boot, then
`cmp work/ring62.raw work/ring63.raw` (must differ = a real new boot), and
look for the key lines above, a display off/on transition, new surface or
swap activity, `^SMP ` samples, AKS sel 9/12, and `PRA touch` (the IC path
must be back - 0 lines means the cmdline regressed again).
The ring header is sometimes stale: trust the decoded text and the NUL
end, not the header total. The swap log is capped at 16 entries and skips
masked surfaces - it is never a frame count and its absence is never a
failure signal.

DO NOT REDO
- Do not re-run the bottom-edge swipe (0196/T20): delivered, not accepted,
  a repeat adds nothing.
- Do not treat the senderID as a signal (ring61 and ring62 both log
  0x100000131) or read frames from swap lines.
- Do not boot without `pratouch=1 pratouchreset=1` and then claim anything
  about touch or tap.
- Do not count `SWEET HID: touch` lines as contacts (only transitions log;
  the queue counter is the volume) and do not claim swipe lines prove
  backboardd dispatched - drain proves userland READ the queue.
- Do not re-open the 4 B/queue-stride question; it is the entry header.
- "-1,-1 was a linkage bug": no, it was the uninitialized panel clamp
  (T17), fixed by 0194, proven by 0195 and reproduced in ring62.
- "AKS sel-8 is the blocker": exonerated in T16, still background churn.
- "sweetiolog / sweet_keys_init will trace it": both dead on this eMMC
  phone (0049 board gate; 0161's sweet_ufs probe never attaches).
- "Boot a setup-complete root to bypass the lock screen": not a
  discriminator - such a phone still boots to the lock screen.
- "The display woke after swipe 2": no, the touch-free ring61 has the same
  `display on` / `sel 79` / `swap 6` triple.

FACTS YOU CAN RELY ON
- The IC is in app mode (32 B descriptor hdr=0x20 bcd=0x100, input reg 0x3)
  and 0194's clamp is effective at runtime (2000,3000 -> 1079,1919).
- backboardd maps both queues, arms both wake-ups, drains them (T16:
  641 events = 151,276 B through 16,384 B, drop=0; T20: head==tail).
- One touch() call = one 236 B event, no coalescing.
- The donor's `0058-sweet-hid-event-services.patch` is byte-identical to
  the PRA's, so the event-construction code is the code that drives
  SpringBoard on the A5 board.
- Git head at handoff 927c84e; CI 45050754773 SUCCESS on ad66e4c with 0
  patch skips and the `SWEET HID: swipe` strings assert passing.

RULES
- Flash only p27 via tools/pra_flash_skip.sh, readback-verified; blanket
  approval exists for that exact command. Never boot without
  pralog=1 praloglba=794623.
- Serials via the PRA_SERIAL env only; never write a serial into git; never
  commit raw rings (work/ringNNN.raw, *-full.txt).
- Every durable calculation via python3/bc with the output quoted; label
  claims VERIFIED / INFERRED / UNKNOWN.
- Three-way patch verify (GNU patch --fuzz=0, git apply, byte cmp), one
  yml marker assert per landed patch, 0 skips in CI.
- Review new patches with
  MODEL='opencode/deepseek-v4.1-flash-free#high' PROMPT=work/validator-prompt.md \
  bash /home/kamion008/Ai/review.sh <claim> <evidence> <patch>
  and fix every refuted finding; escalate anything touching the latch/state
  machine or Apple-private routing rather than guessing.
- Commit subject `pra: ...`, no AI footer; push master and trigger CI.
- Do not commit work/ci*/ , work/pkt-* or shim/pra/out* artifacts.

DELIVERABLE
Land 0198 with three-way verify, one yml marker assert and a review round;
package and flash p27; boot with `pratouch=1 pratouchreset=1 pratouchdbg=1
pratouchselftest=1` plus the new power-key arg and the sampler aimed at
SpringBoard/backboardd; pull the ring from TWRP BEFORE any next boot;
decode whether the non-digitizer event was accepted; then update
work/boots.md (T21 row), write the next handoff, update claim/evidence,
rewrite this prompt, commit, push, trigger CI, and report exactly what the
ring showed and what remains unproven - as a branch, never as a pass or a
fail unless the display demonstrably changed.

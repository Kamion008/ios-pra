You are taking over the PRA Touch investigation: running the unmodified
iPhone X iOS 16.7.16 userland on a Huawei PRA-LX1 (Kirin 655/hi6250) via
an Android boot image, the shim/pra EL1 loader and a ported XNU
8796.141.3. The phone reaches the iOS lock screen; the display is live;
the kernel touch path (touch IC -> HID queue -> backboardd) is fully
proven; the UI ignores every touch. You may change the kernel only -
iPhone X userland stays unmodified.

READ FIRST, IN THIS ORDER
1. ios/ios-pra/HANDOFF_2026-11-22.md - the full state, the proven/refuted
   list, the T20 design, the T20 OUTCOME section at the end and the T21
   plan. It is the source of truth.
2. ios/ios-pra/AGENTS.md - build/flash/log mechanics, patch hygiene, the
   arithmetic rule, safety rules.
3. ios/ios-pra/work/claim-0197.md and work/evidence-0197.md - what T20
   proved, what it refuted, and the confound that makes T20 swipe-only.
   Background: work/claim-0196.md (the swipe patch), work/0196-review.txt.

WHERE THINGS STAND (T20 IS DECODED - BRANCH 2)
T20 booted 0196, the synthetic bottom-edge unlock swipe, and ring62 was
pulled from TWRP and decoded. All three gestures fired exactly as designed
(540,1914 down -> 8 moves -> 540,714 up), the control fired first (raw
2000,3000 -> 1079,1919 edge), the queue drained every event (head==tail
4/4, drop=0, exactly one 236 B event per touch() call), and NOTHING
accepted it: SpringBoard AKS sel 9 = 0 and sel 12 = 0, exactly the ring61
baseline, and the user reports the lock screen unchanged. T20 is NOT a
pass and NOT a fail - it is decode-ladder branch 2, "delivered, not
visibly accepted".

THE CONFOUND YOU MUST NOT REPEAT: T20's cmdline carried
`pratouchswipe=420 pratouchselftest=1 pratouchdbg=1` but NOT `pratouch=1`
and NOT `pratouchreset=1` (T19 had both). So the touch IC was never
brought up this boot and the user's own taps during T20 were no-ops by
construction. The swipe still fired because 0196 arms its timer
unconditionally in SweetHIDTouch::start(), while `pratouch` is parsed only
in the 0172 probe. Restore both args in every touch boot.

THE OPEN QUESTION (unchanged, three branches)
Where the digitizer stream dies downstream of a proven-good queue:
(i) the gesture is rejected at the HID layer (event shape / flags),
(ii) backboardd's HIDEventSystem drops it before dispatch,
(iii) backboardd dispatches and SpringBoard never accepts it.
A negative swipe does not separate these. T20 did not try to.

NEXT ACTION = T21, THE NON-DIGITIZER CONTROL (one kernel-side patch)
Add a boot arg (suggested `pratouchbtn=N`) that fires ONE synthetic power
(consumer page) key down+up N seconds after the touch service starts,
through SweetHIDButtons' own enqueue path - the queue backboardd already
maps and arms (`queue mapped` / `notify armed by SweetHIDButtons` x2 in
every touch-era ring). This is the cheapest possible separator:
- The display turns off / the lock state changes: HID -> backboardd ->
  SpringBoard IPC WORKS. The defect is then the digitizer event shape or
  the digitizer client's registration -> log the event fields backboardd
  receives and compare them with the 0058 donor stream (byte-identical
  code that drives SpringBoard on A5XELTE).
- Nothing at all happens: the failure is generic to this port, not
  touch-specific -> branch (iii), and the next probe is the mach IPC
  boundary between backboardd and SpringBoard.
Bundle in the same boot, at no extra cost: `pratouch=1 pratouchreset=1`
(finger path live, confound gone) and `sweetsample` aimed at SpringBoard
(or backboardd) instead of Setup - the sampler has NEVER been aimed at
either process on this phone, and that is still UNTRIED.
Do NOT re-run the T20 swipe as-is. If a digitizer retry is wanted, change
the shape or the timing deliberately and say why in the claim.

FACTS YOU CAN RELY ON (do not re-derive)
- 0195/T19 proved the clamp at runtime: `selftest raw 2000,3000` ->
  `touch 0 down/up at 1079,1919 edge`; 579 reports, 2.8% read errors,
  36 in-bounds transitions over 840 s. T20 reproduced the clamp on a
  second boot (ring62:980-983).
- 0192/T16 proved delivery: 236 B events, senderID nonzero, head==tail at
  22/22 samples, 641 events = 151,276 B through a 16,384 B queue (9.2x),
  drop=0. T20 re-proved it with a synthetic source (enq 0/2/12/22,
  head==tail 4/4).
- One touch() call = one event, no coalescing (ring62 enq deltas +10 per
  swipe run of 10 calls).
- The senderID is per-boot registration order, NOT a signal: ring61 and
  ring62 both log 0x100000131; T16 logged 0x100000126 (delta 11).
- SpringBoard was alive across the T20 swipe window: the lock screen was
  presented at line 1135 and SpringBoard created five more surfaces after
  swipe 1 (ids 4-6 @2291-2294, ids 7-9 @2431-2433).
- AKS sel 9/12 are absent from BOTH rings, so they are not an acceptance
  signal: with a working port they may never be the right observable.
- Swap lines cannot count frames: the 0046 log caps at 16
  (`if (sweet_fb_swaps_logged < 16)`) and skips masked/null-surface draws;
  ring62 printed 8 lines with counters reaching 15. Absent swaps after a
  static-frame gesture is NOT failure.
- AKS sel-8 was exonerated in T16. sweetiolog is compiled only for SWEET
  and sweet_keys_init only runs from 0060's sweet_ufs probe, which never
  attaches on this eMMC phone - both still produce zero lines.

RULES
- Flash only p27 via tools/pra_flash_skip.sh, readback-verified; blanket
  approval exists for that exact command. Never boot without
  pralog=1 praloglba=794623.
- Serials via the PRA_SERIAL env only; never write a serial into git.
- Never commit raw rings (work/ringNNN.raw, *-full.txt) - the decode and
  the claim/evidence are the durable artifacts.
- Every durable calculation via python3/bc with the output quoted; label
  claims VERIFIED / INFERRED / UNKNOWN.
- Three-way patch verify (GNU patch --fuzz=0, git apply, byte cmp), one
  yml marker assert per landed patch, 0 skips in CI.
- Review new patches with
  MODEL='opencode/deepseek-v4.1-flash-free#high' PROMPT=work/validator-prompt.md \
  bash /home/kamion008/Ai/review.sh <claim> <evidence> <patch>
  and fix every refuted finding. For anything touching the latch/state
  machine or Apple-private routing, escalate rather than guess.
- Commit subject `pra: ...`, no AI footer; push master and trigger CI.
- Do not commit work/ci*/ , work/pkt-* or shim/pra/out* artifacts.

DELIVERABLE
Build and land 0197 (the non-digitizer control) with three-way verify, a
yml marker assert and a review round; package and flash p27; boot with
`pratouch=1 pratouchreset=1 pratouchdbg=1 pratouchselftest=1 pratouchbtn=N`
plus the sampler aimed at SpringBoard; pull the ring from TWRP BEFORE any
next boot; decode whether the power key produced a visible reaction; then
update work/boots.md (T21 row), the handoff, claim/evidence-0198, rewrite
this prompt for the next session, commit, push, trigger CI, and report
exactly what the ring showed and what remains unproven.

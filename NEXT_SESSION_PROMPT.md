You are continuing the PRA Touch investigation on a Huawei PRA-LX1 (Kirin
655/hi6250) booting ported Apple XNU. The phone is in TWRP (serial
57U7N17912003349); if it is still on XNU, ask the user to return it to TWRP
(the ring can only be pulled there).

READ FIRST
1. ios/ios-pra/HANDOFF_2026-11-22.md (T20 status, 0196 design, the frame
   census, decode criteria).
2. ios/ios-pra/AGENTS.md (mechanics, patch hygiene, arithmetic rule).
3. ios/ios-pra/work/claim-0196.md + work/evidence-0196.md + work/0196-review.txt.

STATE
T20 = 0196 (the synthetic bottom-edge unlock swipe) booted 2026-11-22
16:49:39 UTC: `pratouchswipe=420 pratouchselftest=1 pratouchdbg=1`, image
9d32d5f5..., kernel 09eb30b/0b3992b, CI 45044712490 SUCCESS. The swipe
fires at ~420/540/660 s. The ring62 pull and decode are the next action.

DO
1. Pull ring62 with tools/pra_readlog.sh and decode: swipe start/move/release
   lines; the 0195 selftest control; SpringBoard AKS sel 9/12 after a swipe.
2. If the screen is past the lock screen (ask the user / look), TOUCH IS
   DONE - record the outcome and hand off.
3. If the lock screen is unchanged and no AKS: the gesture was drained by
   the kernel but not accepted visibly. Do not re-run the same swipe; move
   the probe inside backboardd/SpringBoard (sweetsample=SpringBoard or
   backboardd, or a backboardd HIDEventSystem log), still with unmodified
   iPhone X userland.
4. No `SWEET HID: swipe` lines: the timer never fired - add a failure log to
   the arming block (the current block is silent on addEventSource failure).

RULES
- Flash only p27 via pra_flash_skip.sh; PRA_SERIAL env only; blanket
  approval exists for the flash command.
- Never boot without pralog=1 praloglba=794623.
- Every durable calculation via python3/bc with quoted output; label
  VERIFIED/INFERRED/UNKNOWN.
- Three-way patch verify, yml assert per patch, 0 skips in CI.
- Commit "pra:" subject, no AI footer, push master, trigger CI.

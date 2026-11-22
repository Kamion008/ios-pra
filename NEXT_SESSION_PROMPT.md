You are continuing the PRA Touch investigation on a Huawei PRA-LX1 (Kirin 655/hi6250) booting ported Apple XNU. The device is a phone in TWRP (serial 57U7N17912003349, battery ~100%).

CONTEXT — read these first (in order):
1. ios/ios-pra/HANDOFF_2026-11-21.md — single source of truth for status, verified facts, refuted theories, do-not-do list.
2. ios/ios-pra/AGENTS.md — stable mechanics (build/package/flash/log, patch hygiene, arithmetic rule, safety).
3. ios/ios-pra/work/evidence-ring61.md — the T19 ring61 decode (the result of the session just finished).
4. ios/ios-pra/work/claim-0195.md — K1-K6 + the appended K7-K11 T19 outcome.

WHERE THINGS STAND (T19 / commit fa74e91 / CI 44930621178 — SUCCESS, flashed to p27 readback-verified)

The KERNEL touch path is now FULLY PROVEN end-to-end, and the userland delivery is proven drained:
- The 0194 clamp IS effective at runtime: `SWEET HID: selftest raw 2000,3000` → `touch 0 down/up at 1079,1919 edge` (ring61 lines 1001-1007). -1,-1 and unclamped 2000,3000 both absent. Falsifier K3/K6 HIT.
- 84 telemetry samples over 840 s (14.0 min; python3: 84000*0.010=840); final `reports=579 errs=16 corrupt=0 reads=82451`; 36 touch transitions (18/18 down/up) ALL in-bounds 0..1079/0..1919; `-1,-1` nowhere.
- Queue mapped x2, notify armed x2, `queue stats enq=514 drop=0 type=11 head=9600 tail=9600`; 514 events x 236 B = 118.5 KiB through the 16 KiB queue = 7.4x overflow, drop=0, head==tail every sample (the T16 drain proof — userland reads everything intact).
- SpringBoard reached; display live (9 swaps, 1080x1920 surfaces); no panic.

THE BLOCKER: the iOS UI (lock screen) showed NO reaction to any touch, despite the user tapping/swiping many times. The kernel delivers real, drained events; backboardd does not route them to SpringBoard's gesture recognizers — same rung T16 named (claim-0192).

NEW INFERENCE (claim-0195 K11): every PRA touch test was on the LOCK SCREEN (empty com.apple.SetupDone.plist bypass). The working donor evidence was on the HOME SCREEN after Setup was marked complete (sweet donor v14 purplebuddy data_ark path; A5 0123 / herolte 0216). An inert lock screen with a working delivery path is not excluded.

DELIVERABLE FOR THIS SESSION
Get iOS past the lock screen to the home screen, then touch and decode whether the UI reacts.

PLAN
1. Decide the home-screen route:
   (a) Seed the donor's com.apple.purplebuddy.plist (SetupDone/SetupFinishedAllSteps/SetupVersion=11) plus the data_ark activation state into tools/mkiosroot.sh — the donor's proven path (ios-sweet/NOTES.md v14).
   (b) Or press the physical Home button on the lock screen to reach the home screen (Home already reaches HID per donor 0211), then touch.
2. Build/package (same cmdline defaults via tools/pra_package.sh; keep pralog=1 praloglba=794623), flash p27 with readback verify (blanket user approval exists for the flash command), boot, leave >60 s, return to TWRP.
3. Pull the ring with tools/pra_readlog.sh (NUL-end fix now in place — do NOT trust a 35,665-byte readout; check for the stale-header NOTE), decode whether touch now produces a UI reaction.

DECODE CRITERIA (per claim-0195)
- TOUCH WORKS (UI reacts): SWEET HID touch lines with real coords + the UI responds on screen → DONE, hand off.
- UI still dead with real drained events: blocker is inside backboardd's HIDEventSystem routing → compare event format/display identity vs the donor working path (research/herolte-ref, ios-sweet/NOTES.md).

AGENTS.md RULES (follow exactly)
1. EVERY calculation in a durable artifact (claim, boots.md row, handoff entry) must be computed with python3/bc and the tool output quoted beside the result — NO mental math.
2. Every durable claim labeled VERIFIED / INFERRED / UNKNOWN.
3. Flash only p27 via pra_flash_skip.sh; battery ≥25%; you have blanket approval for the flash command (exact command shown first: `PRA_SERIAL=57U7N17912003349 bash tools/pra_flash_skip.sh out/pra-xnu.img`).
4. Never boot without pralog=1 praloglba=794623.
5. Serials via PRA_SERIAL env only, never in git.
6. Patch hygiene: three-way verify (git apply --check, GNU patch --fuzz=0 --dry-run, git apply), structural assertions, yml assert for each new patch, 0 skips in CI.

FILES TO TOUCH (authoring allowed): work/boots.md (add T20 row), HANDOFF_2026-11-21.md or a new HANDOFF_2026-11-22.md with the session outcome, work/claim-0195.md or a new claim file, tools/mkiosroot.sh (only if route (a)), work/evidence-*.md (ring decode), NEXT_SESSION_PROMPT.md (for the session after).

COMMIT/PUSH: commit with single "pra:" subject (no AI footer), push to master, trigger CI. Do not modify untracked files except those you are authoring for this fix; do not flash anything but p27.

PRA_SERIAL=57U7N17912003349 (device in TWRP)
You are taking over the PRA Touch investigation: running the unmodified
iPhone X iOS 16.7.16 userland on a Huawei PRA-LX1 (Kirin 655/hi6250) via
an Android boot image, the shim/pra EL1 loader and a ported XNU
8796.141.3. The phone reaches the iOS lock screen; the display is live;
the kernel touch path (touch IC -> HID queue -> backboardd) is fully
proven; the UI ignores every touch. You may change the kernel only -
iPhone X userland stays unmodified.

READ FIRST, IN THIS ORDER
1. ios/ios-pra/HANDOFF_2026-11-22.md - the full state, the proven/refuted
   list, the T20 design and the decode ladder. It is the source of truth.
2. ios/ios-pra/AGENTS.md - build/flash/log mechanics, patch hygiene, the
   arithmetic rule, safety rules.
3. ios/ios-pra/work/claim-0196.md, work/evidence-0196.md and
   work/0196-review.txt - the swipe patch and its review record.

WHERE THINGS STAND
T20 boots 0196, a synthetic bottom-edge unlock swipe. The phone booted
XNU at 2026-11-22 16:49:39 UTC with `pratouchswipe=420
pratouchselftest=1 pratouchdbg=1` (image sha256 9d32d5f5..., kernel
6c12dec7..., CI 45044712490 SUCCESS) and was not enumerating adb at
17:02 UTC. The three gestures were due ~16:56:39, ~16:58:39 and
~17:00:39 UTC. Ring62 has NOT been pulled; the swipe result is UNKNOWN.
Do not treat T20 as pass or fail before the decode.

FIRST ACTION
Run `adb devices`. If the PRA-LX1 is in TWRP, pull ring62 immediately
(before any boot or power cycle - a new XNU boot overwrites the ring):
```
PRA_SERIAL=<serial from adb devices> \
  OUT=work/ring62.raw TXT=work/ring62-full.txt tools/pra_readlog.sh
cmp work/ring61.raw work/ring62.raw     # must differ (new boot)
```
If it is not in TWRP, ask the user two things and stop:
(1) does the screen show the lock screen or the home screen? (this is a
decisive signal the ring cannot show), and (2) return the phone to TWRP
without booting XNU again.

DECODE (exact greps in the handoff)
Look for `SWEET HID: swipe 1 start (interval 420 s) at 540,1914`,
`move 1/8` .. `move 8/8`, `swipe 1 release at 540,714`, runs 2 and 3,
and the control `SWEET HID: selftest raw 2000,3000`. Check SpringBoard
AKS sel 9/12 (baseline 0) and new `SWEET FB: swap` lines (capped log,
bonus only).
- Swipe lines + home screen and/or AKS sel 9/12: TOUCH IS DONE. Record
  the outcome row, update the handoff, commit `pra: ...`, push, trigger
  CI.
- Swipe lines + unchanged lock screen + no AKS: the event reached
  backboardd but was not visibly accepted. Do NOT re-run the same swipe.
  Separate gesture-rejected vs dispatch-drop vs SpringBoard-never-routed
  with kernel-side probes only (see the handoff's branch list).
- No swipe lines at all: the timer never fired (the arming block is
  silent on parse/addEventSource failure). Add a failure log or a direct
  start-time call, rebuild, reflash.

FACTS YOU CAN RELY ON (do not re-derive)
- 0195 proved the clamp at runtime: `selftest raw 2000,3000` ->
  `touch 0 down/up at 1079,1919 edge`; 579 reports, 2.8% read errors,
  36 in-bounds touch transitions over 840 s.
- 0192 proved delivery: 236 B events, senderID 0x100000126, head==tail at
  22/22 samples, 641 events = 151,276 B through a 16,384 B queue (9.2x)
  with drop=0.
- 0194/ring58: -1,-1 was the uninitialized panel clamp in the compiled
  A5XELTE arm, not a linkage bug.
- Swap lines cannot count frames (16-line cap, mask/null-surface skips);
  the lock screen is a static CPU-rendered image, so absent swaps is not
  failure.
- AKS sel-8 was exonerated; the sampler has only ever been aimed at Setup
  on this phone; sweetiolog and sweet_keys_init never attach here.

RULES
- Flash only p27 via tools/pra_flash_skip.sh, readback-verified; blanket
  approval exists for that exact command. Never boot without
  pralog=1 praloglba=794623.
- Serials via the PRA_SERIAL env only; never write a serial into git.
- Every durable calculation via python3/bc with the output quoted;
  label claims VERIFIED / INFERRED / UNKNOWN.
- Three-way patch verify (GNU patch --fuzz=0, git apply, byte cmp), one
  yml marker assert per landed patch, 0 skips in CI.
- Review new patches with:
  MODEL='opencode/deepseek-v4.1-flash-free#high' \
  PROMPT=work/validator-prompt.md \
  bash /home/kamion008/Ai/review.sh <claim> <evidence> <patch>
  and fix every refuted finding.
- Commit subject `pra: ...`, no AI footer; push master and trigger CI.
- Do not commit work/ci*/ , work/pkt-* or shim/pra/out* artifacts.

DELIVERABLE
When the decode is done: update work/boots.md's T20 row, append the
outcome to the handoff (and claim/evidence if the swipe taught something
new), rewrite this prompt for the next session, commit, push, trigger CI,
and report exactly what the ring showed and what remains unproven.

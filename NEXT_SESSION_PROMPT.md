NEXT SESSION PROMPT - PRA Touch, after T21c (2026-11-22c)

You are continuing a 9-day bring-up: the unmodified iPhone X iOS 16.7.16
userland now boots on a Huawei PRA-LX1 (Kirin 655) and, as of the last boot,
TOUCH WORKED and the phone was used. Read HANDOFF_2026-11-22c.md first (it
supersedes 11-22b and is self-contained), then AGENTS.md for mechanics.

FIRST ACTION (no boot required, do this before anything else)
The phone should be idle in TWRP with ring64 unread and a brand-new boot's
worth of userland log unharvested. Pull the ring, then re-harvest the
tracev3 archives:

  PRA_SERIAL=<serial> OUT=work/ring64.raw TXT=work/ring64-full.txt \
    tools/pra_readlog.sh
  cmp work/ring63.raw work/ring64.raw          # must differ = new boot
  TXT=work/ring64-full.txt RAW=work/ring64.raw sh work/0198/decode-ring63.sh

and then repeat the block-wise HFSX read from work/userland-logs-2026-11-22.md
(no HFS+ driver in TWRP: read the volume in 4 KiB blocks via `dd bs=4096`,
resolve the catalog fork through the extents-overflow B-tree; toybox `dd`
writes its stats line to stdout). Grep the harvested archives for:
`digitizerEnabled`, `digitizerWake`, `backlight-off`, `BKDigitizerStreamClient`,
`tapToWake`, `digitizer:%llX - display:`.

THE QUESTION YOU ARE ANSWERING
Touch works but INTERMITTENTLY, and the user reports it tracks the synthetic
power button; they never pressed the physical one. Candidate causes, none
excluded yet: (a) the synthetic POWER key (0x30) from 0198/0199 wakes the
digitizer, (b) the volume-up pair does, (c) elapsed time / SpringBoard
bring-up, (d) a combination. The evidence that makes (a) most likely is
backboardd's own log: the winning `BKSHIDUISensorMode` carries
`digitizerEnabled: NO` with `display: off` and reason `idle timer`, and a
wake flips it to the awake mode (`digitizerWake: YES; display: on`). So the
digitizer is administratively disabled while the panel is considered asleep,
not rejected for its event shape.

WHAT WOULD SETTLE IT
- ring64: the 30 s `powerkey N down` cadence vs the first `SWEET HID: touch`
  transitions, and the buttons-queue `enq` / `head == 64*enq` accounting.
- the tracev3 harvest: does `digitizerEnabled` flip to YES right after a
  press and back to NO on the idle timer?

THEN, IN ORDER
1. Flash 0201 (already landed; kernel built from 7f20894) - it only
   instruments: RequestPowerChange with the raw argument, notification
   registrations, `setElementValue`/`setProperties` pushes from backboardd,
   plus the one behaviour change that our digitizer events now carry
   `kIOHIDEventFieldDigitizerIsDisplayIntegrated`. Package with the T21c
   cmdline and `tools/pra_flash_skip.sh`.
   If NO `setElementValue`/`setProperties` line ever appears, backboardd
   never configures us through the event service: 0202 is the wrong lever and
   the tracev3 route log is the way forward.
2. Write 0202: publish `MultitouchHostStateKeys` (`ScreenOn`,
   `DigitizerSurfaceCovered`, `PocketTouchesExpected`, ...) and accept the
   host-state usages in `setElementValue`. 0203 (display power honesty) comes
   LAST because it can blank the panel.

BOOT ARGS - MANDATORY UNTIL 0202 LANDS
Any touch experiment must carry `pratouch=1 pratouchreset=1 pratouchdbg=1
pratouchselftest=1 prapowerkey=900 prakeyevery=30` plus
`sweetsample=SpringBoard,backboardd`. Without the power-key args the boot
will look exactly like every pre-T21 boot: nothing happens. The T21c cmdline
is work/0199/cmdline.txt (532 B) and the packaging gate checks the 11
critical args.

DO NOT REDO (all refuted or already measured - details in the handoff)
- The `{{0,0},{1,1}}` digitizer rect is `normalizedDigitizerRect` in 0..1
  space: correct. Do not publish a pixel rect.
- `events:0` in the BKIOHIDService line is a matched-transition snapshot, not
  a drop counter.
- `A5XELTE FB: display-off request ignored (keep_on)` is baseline noise (1-3
  per boot across rings 34-63 with no key press). It is not a positive.
- SpringBoard's digitizer stream client exists; the service is matched,
  builtin and authenticated. The consumer was never the problem.
- The digitizer event shape, senderID and queue accounting are fine.
- A passive swipe with no wake ahead of it proves nothing.

FACTS YOU CAN TRUST
- Anything in HANDOFF_2026-11-22c.md marked VERIFIED.
- 0201's marker assert lesson: assert on text that appears contiguously in
  the binary (`setElementValue page 0x%x`), not across a `%s`.
- 0200's patch header claim about which timer "is armed first" is wrong; the
  order of the two log lines is not guaranteed.

RULES
AGENTS.md is authoritative: kernel-side only; flash p27 via
tools/pra_flash_skip.sh with readback; never p30/p32/bootloaders; never boot
without pralog=1 praloglba=794623; serials via PRA_SERIAL only; every durable
number from a quoted python3/bc; three-way patch verify plus a contiguous
marker assert; `pra: ` commit subjects, no AI footer; push master and
dispatch CI with RUNNER=macos-15 (a push-triggered run targets A5XELTE -
cancel it); battery >= 25%.

DELIVERABLE
The answer to "does a wake event re-enable the digitizer, and what makes
backboardd believe the panel is awake" - as evidence, then as a patch that
makes touch work from boot with NO synthetic key, recorded in boots.md,
claim-XXXX.md and a new dated handoff.

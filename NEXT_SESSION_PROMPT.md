NEXT SESSION PROMPT - PRA Touch, after HANDOFF_2026-11-23d (2026-11-23d)

You are continuing a 9-day bring-up: the unmodified iPhone X iOS 16.7.16 userland boots on a Huawei PRA-LX1 (Kirin 655) and TOUCH WORKED in T21c, but only via a synthetic wake key. Read HANDOFF_2026-11-23d.md first (supersedes 11-22c, self-contained), then AGENTS.md for mechanics.

THE QUESTION IS NOW ANSWERED BY EVIDENCE: a wake event DOES re-enable the digitizer, and backboardd believes the panel is awake because SpringBoard publishes an asserted BKSHIDUISensorMode (score 4108 vs backboardd's baseline 1) carrying digitizerEnabled: YES, displayState: on, reason backlight-on/DeviceWake, changeSource LockButton, multitouchHostStateKeys including WakeOnTapEnabled — while the idle timer's backlight-off mode carries digitizerEnabled: NO; displayState: off. The synthetic 0x30 POWER key from 0198/0199 was acting as that wake (candidate cause (a) confirmed). The digitizer events were never rejected for shape — they arrived while administratively disabled.

REMAINING WORK: make touch work from boot with NO synthetic key, via 0202 (publish MultitouchHostStateKeys + accept host-state usages in setElementValue) then 0203 (display power honesty, LAST — can blank the panel). 0201 is already built and packaged locally but NOT flashed.

FIRST ACTION (no boot required, do this before anything else — but it's done; verify state):
- Ring64 pulled & decoded (work/ring64-*: 113 pairs, head==64*enq OK, arm line landed t=890.9s, selftest t=267s).
- Tracev3 re-harvested (work/harvest-2026-11-23/: Persist-34..38, launchd.log.1=T21c).
- Causality evidence extracted (extract-34-36-38.txt): LockButton→digitizerEnabled YES/on; idle timer→NO/off.
- 0201 packaged locally: shim/pra/outxnu/pra-xnu.img (6039552 B), T21c cmdline 532 B, all 11 critical args present, CI 45075755692 SUCCESS (commit 7f20894).
- CI build tree for three-way verify: /tmp/opencode/ci-tree-0201/src/.

THEN, IN ORDER
1. FLASH 0201 (requires user approval — show the exact command first). Package already done: shim/pra/outxnu/pra-xnu.img. Flash with tools/pra_flash_skip.sh (p27 only, readback-verified), T21c cmdline:
   pratouch=1 pratouchreset=1 pratouchdbg=1 pratouchselftest=1 prapowerkey=900 prakeyevery=30 sweetsample=SpringBoard,backboardd
   Mandatory until 0202 lands: every touch experiment carries those args plus pralog=1 praloglba=794623 and the 11 critical args. Without the power-key args the boot looks like every pre-T21 boot: nothing happens. Battery >= 25%.
   After boot, pull the ring and grep for:
   - `SWEET HID: SweetHIDTouch setElementValue page` / `setProperties key`  (backboardd pushing host state)
   - `SWEET FB: powerreq n=` (display-off requests from userland)
   - `SWEET FB: notifyreg type` (display notification subscribers)
   - `SWEET FB: swap ... while userland-display-off` (state split)
   - `SWEET HID: digitizer events marked display-integrated` (once per boot, before first touch)
   If NO setElementValue/setProperties line ever appears → backboardd never configures through the event service → 0202 is the wrong lever, fall back to the tracev3 route log instead of writing 0202.

2. WRITE 0202 (only if 0201 shows the push):
   - SweetHIDTouch::start(): publish MultitouchHostStateKeys as OSArray of OSString with ScreenOn, DigitizerSurfaceCovered, PocketTouchesExpected (honourable from fPowerOff/board data). Add WakeOnTapEnabled only with item 3, never before.
   - Publish SurfaceDimensions dict next to SurfaceWidth/SurfaceHeight/DisplayIntegrated.
   - IOHIDEventService::setElementValue: accept the host-state usages, store them, log transitions, return kIOReturnSuccess; keep kIOReturnUnsupported for everything else.
   - SweetHIDTouch::touch(): set kIOHIDEventFieldDigitizerIsDisplayIntegrated on collection and every child; set Will/DidUpdateMask so parent+children are non-zero (backboardd's `ignoring subevent with nonzero didUpdateMask` check).
   - Marker assert: a contiguous substring that actually appears in the binary (the 0201 lesson).
   - Three-way verify: stage scripts + git apply of full stack (zero skips), GNU patch --fuzz=0 --dry-run on index-stripped diffs, byte cmp against post file.
3. WRITE 0203 LAST (can blank the panel): drop a5fb_keep_on=1 for the test so RequestPowerChange applies; send notify() on power transitions for registered types; publish DisplayPowerOff read-back. Do 0201/0202 first.

BOOT ARGS - MANDATORY UNTIL 0202 LANDS
Any touch experiment: pratouch=1 pratouchreset=1 pratouchdbg=1 pratouchselftest=1 prapowerkey=900 prakeyevery=30 sweetsample=SpringBoard,backboardd plus pralog=1 praloglba=794623 and the 11 critical args. The T21c cmdline is work/0198/cmdline.txt (532 B base) + prakeyevery=30; the packaged gate checks the 11 critical args. Never boot without pralog=1 praloglba=794623.

DELIVERABLE
Touch works from boot with NO synthetic key; recorded in boots.md, claim-XXXX.md, and a new dated handoff. Until then the answer stands as evidence: wake re-enables the digitizer; SpringBoard's asserted LockButton sensor-mode (score 4108, multitouchHostStateKeys incl. WakeOnTapEnabled) is what makes backboardd believe the panel is awake.

RULES (AGENTS.md authoritative): kernel-side only; flash p27 only via pra_flash_skip.sh with readback; never p30/p32/bootloaders; serials via PRA_SERIAL only; durable numbers via python3/bc quoted and labelled VERIFIED/INFERRED/UNKNOWN; commit subject `pra: ...`, no AI footer; push master and trigger CI with RUNNER=macos-15 (push-triggered run targets A5XELTE — cancel it); battery >= 25%; get explicit user approval (exact command shown first) before any flash.

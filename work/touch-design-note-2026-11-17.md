# Touch design note — CYTT21403 -> IOKit HID -> SpringBoard (2026-11-17)

Evidence labels: VERIFIED = file:line or ring text quoted; INFERRED/UNKNOWN marked.
All paths relative to /home/kamion008/Ai/ios/ios-pra. 0172 = xnu/patches/0172-pra-touch-probe.patch.

## 1. The report->HID path in THIS port (components that already exist)

The whole userspace side is ALREADY BUILT AND LIVE on PRA; only the driver->inject call is missing.

1. `SweetHIDTouch : IOHIDEventService` (digitizer service) — xnu-src/iokit/Kernel/arm/hid/SweetHID.cpp:359-376;
   committed source: xnu/patches/0058-sweet-hid-event-services.patch:20947-20962.
2. Personality match: KernelConfigTables entries `'IOClass'=SweetHIDTouch, IOProviderClass=IOResources`
   (0058 patch:14-27) — instantiated without any Apple platform expert. VERIFIED live: work/ring34.txt:707
   "SWEET HID: SweetHIDTouch open by IOHIDEventServiceUserClient -> 1" (backboardd opened it on a PRA boot;
   also ring33.txt:1316, ring30.txt:824).
3. What backboardd expects: services advertise `HIDServiceSupport=true` + `IOUserClientClass=
   IOHIDEventServiceUserClient` (SweetHID.cpp:96-98; contract stated SweetHID.cpp:5-9: backboardd opens
   type 'esuc' and reads serialized IOHIDEvents from the user client's shared queue).
4. Event dispatch: `sweet_hid_touch(finger, down, x, y)` (SweetHID.cpp:566-571) -> `SweetHIDTouch::touch`
   (SweetHID.cpp:454-549) builds an IOHIDEvent digitizer collection + per-finger children ->
   `IOHIDEventService::dispatchEvent` (SweetHID.cpp:206-224) -> per-client action -> IOHIDEventServiceUserClient
   queue (IOHIDEventServiceUserClient.cpp / IOHIDEventServiceQueue.cpp, compiled via 0058 patch:8-11).
   SpringBoard consumes from backboardd as on the donor — VERIFIED there: A5XELTE_PROGRESS.md:113.
5. Geometry is already correct on PRA: `SweetHIDTouch::start` selects 1080x1920, off 0/0 under
   `ARM64_BOARD_CONFIG_A5XELTE` (SweetHID.cpp:437-440), and PRA builds define A5XELTE too
   (xnu/patches/0130-pra-define-a5xelte-at-compile-time.patch:10). No SweetHID.cpp change needed.
6. Missing piece = only the PRA driver calling `sweet_hid_touch` instead of printf (0172 today),
   plus the IC not yet alive (sec 2). INFERRED: no new IOKit components required.

## 2. What 0172 already does — and the coordinates answer

ANSWER: the 0172 code DOES decode real x/y from touch reports (full TT5 parser), but it has never
produced a coordinate on the device: the HID descriptor read NACKs every boot, so `pra_live` stays
false and no touch report is ever read. In practice today it is raw register/report plumbing only.

- Decode exists (VERIFIED, patch text): `pra_touch_bitfield` 0172:546-557; `pra_touch_parse` 0172:567-609
  decodes count (5 bits @16 from buf+3), per-record id/x/y/p (5@8/16@16/16@32/8@48, records at [7+10*i]) and
  gates x<1080, y<1920, id<10; the worker stores last_contact_* (0172:683-688) and the stats line PRINTS them:
  0172:708-715 `"PRA touch: irq lo/hi=%u/%u idle=%d reports=%u errs=%u corrupt=%u last: slot=%d x=%d y=%d p=%d"`.
- Runtime: work/ring34.txt:10-13 (all rings 29-34 identical): probe OK, COMP_VERSION=3132302a,
  `PRA touch: HID desc read failed err=6 (address NACK)`, then ring34.txt:123
  `... irq lo/hi=1000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1`.
  IRQ histogram never moves off lo (line dead or chip unpowered) — UNKNOWN root cause; WORKLOG sec 9
  ranks "rail state / deep-sleep inheritance" first; fix = rung 2 reset+BL_LAUNCH_APP.
- So: report PARSING = present in code; decoded x/y = never observed; injection = absent by design.

## 3. Donor reference a5xelte_touch.c (donor tree = ios-galaxy-s8, SWEET/A5XELTE)

- Location: donor tree /home/kamion008/Ai/ios/ios-galaxy-s8 holds only patches (0060/0062/0071/0118/
  0119/0120/0122/0123 touch ones); the assembled driver text is in the gitignored CI-tree copy
  xnu-src/bsd/dev/a5xelte_touch.c (979 lines). Donor verification of END STATE: A5XELTE_PROGRESS.md:113
  — 0123 boot: "user reports both touch log lines and an iOS UI response when touching an on-screen item".
- Report->HID path (VERIFIED in that file): NO XNU interrupt routing — a kernel thread polls every 5 ms
  (a5xelte_touch.c:67 "Poll without an unregistered XNU IRQ", :441 a5touch_log_thread); polls the ZT7538
  INT status via the I2C controller, on INTN-low reads a 34-byte packet (:450-452), ACKs (:453), then
  `a5touch_report_packet` (:489-534) validates status/count and per active slot calls
  `sweet_hid_touch(slot, 1, x, y)` (:527); on release re-sends last-known coords (:490, :529);
  error recovery = 8 transfer errors or 600 idle ticks -> bounded power-cycle (:455-470);
  release-all helper (:486-494). Same contract wired by xnu/patches/0060:241,526,531.
- PRA differences (0172 CI guard, .github/workflows/xnu.yml:186-194): i2c2 host at 0xFFD73000 (DesignWare,
  not Exynos HSI2C3), IRQ = gpio224 = pl061 gpio28.0 @ 0xFFF1D000, whole probe behind `pratouch=1`;
  IC is CYTT21403 (TT5/HID-over-I2C) not ZT7538 (mode-0); rails VCI=LDO17/VDDIO=LDO4 via hi6555 PMIC
  (UNKNOWN enable offsets, WORKLOG sec 9); pra_charger.c shares the bus with NO arbitration
  (0172:53-57 hazard note).

## 4. research/driver-specs/touch-work/ — EXISTS, not empty

Files: 0001-pra-touch-probe.patch (landed as 0172), 0002-adt-pra-touch-node.patch (landed as the
mkadt_pra.py edit), WORKLOG.md. Established there (all VERIFIED with cited sources):
- Register map + gpio math + 128 MHz clock rationale: WORKLOG.md sec 2 (i2c2 0xFFD73000/0x1000;
  gpio28 bank 0xFFF1D000, DAT = base+pin*4 bit0, anchored by fingerprint fff1d008 probe).
- TT5 protocol constants: WORKLOG.md sec 2.3 (desc reg 0x0001 32B, input reg 0x0003, report id buf[2]=0x1,
  count 5 bits @16 from buf+3, records [7+10*i], 28-vs-32B discrepancy flagged).
- Transaction forms + budgets: WORKLOG.md sec 3; IRQ decode: sec 4; on-boot behavior contract: sec 5;
  open UNKNOWNs table: sec 9; follow-up ladder (rung 2 reset/launch, 0162 shared i2c layer, rung 5 HID
  injection): sec 10. Plus the rung ladder in research/driver-specs/pra-touch-plan.md (rungs 0-6).

## 5. FIRST TEST after flashing any touch code (project rule: first signal = raw reports in the log)

Single cheapest observation, BEFORE any unlock attempt: boot with `pratouch=1` (appended via CMDLINE,
PRA_ALLOW_ANY_CMDLINE=1 per WORKLOG.md sec 12.7), then pull the ring (`tools/pra_readlog.sh`, cmp vs
previous) and grep -F "PRA touch:". The pass signal = the 0172 worker line with reports>0 and a real
contact, i.e. `PRA touch: ... reports=N ... last: slot=0 x=... y=...` preceded by
`PRA touch: HID desc len=32 bcd=0x100` / "app mode confirmed" (0172:824-840 gates). Rings 29-34 show the
current failing state (NACK, reports=0) — any touch code is judged by THIS line changing, not by UI.
0177 must KEEP this print (it is both the marker and the first test). Second signal (optional, same log):
`SWEET HID: touch N down at x,y` IOLog lines (SweetHID.cpp:543-546) prove injection fired.

## 6. Draft patch plan for 0177 (plan, NOT the patch)

Rung A — make the IC answer (prereq, may be its own patch/boot-arg `pratouchreset=1`, WORKLOG sec 10.3):
  - In bsd/dev/pra_touch.c: readback-verified RST toggle of gpio18.1 (bank @0xE8A1D000, DAT base+0x4,
    gpio145 per 0172:97 comment), then 11-byte BL_LAUNCH_APP frame `0B 00 40 00 01 3B 00 00 CRC CRC 17`
    to the output register (CRC-ITU-T init 0xFFFF over bytes [4..7]), bounded <=300 ms, re-read descriptor.
Rung B — event wiring (the actual 0177):
  - Files: bsd/dev/pra_touch.c (main), iokit/bsddev/IOKitBSDInit.cpp (NO change expected — call site
    already landed, 0172 patch:862-893), .github/workflows/xnu.yml (assert only), bsd/conf/files (NO change).
  - Add `extern void sweet_hid_touch(int, int, int, int);` and call it in the worker where 0172:683-688
    stores last_contact: on press/move `sweet_hid_touch(slot,1,x,y)`, on release
    `sweet_hid_touch(slot,0,last_x,last_y)`; keep a 10-slot down[] table (SWEET_TOUCH_FINGERS=10,
    SweetHID.cpp:375); release-ALL slots on worker error (donor :486-494 pattern); keep the 10 s stats print.
  - Shared pra_i2c arbitration with pra_charger.c (plan sketch 0162) is MANDATORY before event plumbing
    (WORKLOG.md sec 3 hazard + sec 10.4) — either inside 0177 or as its own landed prerequisite patch.
  - No SweetHID.cpp changes: geometry/edge-tip already correct for PRA (SweetHID.cpp:437-440, 0071 edge bits).
  - CI marker string to assert in the same commit: e.g. `grep -F 'PRA touch: hid inject'` (a printf added
    at the injection call site) plus the existing 'PRA touch:' asserts; generate via the work/gen0175.py
    replay method, three-way verify + hostile review (HANDOFF_2026-11-16-c.md sec 5).

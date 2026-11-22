# EVIDENCE — T19 ring61: the 0194 clamp, the self-test, and a full deliverable stream that the UI ignored

Decoded 2026-11-22 from work/ring61.raw (pulled via `tools/pra_readlog.sh` with
the stale-header fix; cmp vs ring60.raw differs at byte 2475 = a real new
boot). All counts below are `grep -n`/python3 on work/ring61-true.txt
(216,150 B, 3,703 lines, full contiguous text from the raw; the earlier
35,665-B readout was the stale-header truncation, fixed in pra_readlog.sh).

## 1. The 0194 clamp — VERIFIED at runtime, no finger needed

work/ring61-true.txt lines 1001-1007 (canonical grep numbering):

```
1001 SWEET HID: SweetHIDTouch open by IOHIDEventServiceUserClient -> 1
1002 SWEET HID: queue mapped by SweetHIDTouch
1003 SWEET HID: selftest raw 2000,3000
1004 SWEET HID: touch 0 down at 1079,1919 edge
1006 SWEET HID: queue stats enq=0 drop=0 type=0 head=0 tail=0
1007 SWEET HID: touch 0 up at 1079,1919 edge
```

- The 0195 self-test fired exactly as designed: the user client's
  clientMemoryForType returned success with `_state == kUserClientStateOpen`,
  and the one-shot call injected raw (2000,3000).
- 0194's clamp `x >= fPanelW ? fPanelW - 1 : x` turned 2000 -> 1079 and
  3000 -> 1919. This is the PREDICTED pass signature (claim-0195 K3):
  `SWEET HID: selftest raw 2000,3000` + `touch 0 down/up at 1079,1919`.
- `-1,-1` did NOT appear. An unclamped 2000,3000 did NOT appear.
- This also confirms the PRA build runs the ARM64_BOARD_CONFIG_A5XELTE arm
  of SweetHIDTouch::start() (fPanelW/H = 1080/1920 as 0194 wrote it).

## 2. The full deliverable stream — VERIFIED, 36 touches with real coords

- 84 telemetry samples, last `lo/hi=84000` = 84,000 x 10 ms polls = 840 s =
  14.0 min of polling (python3: 84000*0.010 = 840).
- `reports=579 errs=16 corrupt=0 reads=82451` final sample (line 3940).
  err rate 16/579 = 2.8% (python3); corrupt=0.
- 36 `SWEET HID: touch` transitions (18 down / 18 up), ALL with real,
  in-bounds coordinates: min (168,907), max (1079,1919) on the 1080x1920
  panel (python3 bounds check: 36/36 in 0..1079 / 0..1919).
- `PRA touch: hid inject slot=0 down x=168 y=907` (line 266) — the IC
  reports parse into real coordinates; `-1,-1` appears nowhere.
- Queue: `SWEET HID: queue mapped by SweetHIDTouch` (1002) and
  `by SweetHIDButtons` (1050); `queue notify armed by SweetHIDButtons` +
  `by SweetHIDTouch` (1055-1056); `queue stats` 15 lines, last
  `enq=514 drop=0 type=11 head=9600 tail=9600` (line 3689).
- Drain proof (the T16 method): 514 events x 236 B = 121,304 B = 118.5 KiB
  through the 16 KiB queue = 7.4x overflow with drop=0, and head==tail at
  every stats sample — userland (backboardd) reads everything.
- The user (2026-11-22, in-session) confirms: many taps/swipes over the
  ~14-min run; the iOS UI (lock screen) showed NO reaction at all.

## 3. The readlog stale-header bug — found and fixed (tools/pra_readlog.sh)

- The pralog header `total` is only rewritten on a flush. This boot was cut
  before its next header flush, so the header still carried ring60's
  `total=35665`; the readlog then printed only the first 35,665 B and the
  decode missed the queue map, the self-test and 34 of the 36 touches.
- Fixed: when `total < ring size`, the tool now takes the first NUL as the
  true end of the written text (the ring cannot have wrapped), printing
  `NOTE: header total ... is stale; using NUL end ...`. Verified by re-pull:
  the fixed tool yields 216,150 B and the cmp-vs-ring61.raw raw matches
  (only the bytes past the ring's end differ).

## 4. The boot state (no panic; UI live)

- Boot marks: launchd 126, backboardd 35, SpringBoard 137, sharingd 4,
  no panic, no hfs error. `exec SpringBoard` at line 514, `exec backboardd`
  at 628.
- Display live: 9 `SWEET FB: swap` lines (1080x1920), `display on`
  (line 2533), SpringBoard created 1080x1920 surfaces (lines 1647/1661)
  plus small icon-size surfaces (272x184, 312x202, 230x186, 360x246...).
- The clock stayed at 16:01:xx in the log; the user's earlier boots showed
  the 4:0x frozen-clock phenomenon (out of scope here).
- Crash traffic: driverkitd sig 9 (known/benign), PosterBoard sig 5
  (crashed once at line 2763, re-exec'd at 2768; 2 execs total — not a
  loop); ReportCrash/ReportMemoryException active. No touch-related crash.

## 5. What this means (labeling per AGENTS.md)

- VERIFIED: 0194 effective at runtime (the self-test clamp, line 1003-1007).
- VERIFIED: the whole kernel touch half works — IC reports -> parse ->
  sweet_hid_touch -> SweetHIDTouch::touch() real coords -> dispatchEvent ->
  queue -> drained by backboardd, drop=0, 7.4x overflow.
- VERIFIED: no -1,-1 anywhere; the T17 clamp bug is gone (falsifier hit).
- VERIFIED (user observation): the UI did not react to any touch.
- INFERRED: the blocker is backboardd-internal (it drains the queue but its
  HIDEventSystem never routes the digitizer events to SpringBoard's gesture
  recognizers) — the same rung T16 named; the SweetHID event/service code
  here is identical to the donor path (A5XELTE 0123 device-verified touch,
  herolte 0216 working touch), so a kernel-side event-format difference is
  the low-probability branch.
- UNKNOWN: the specific userland reason (event disposition, display/edge
  association, HIDEventSystem client state, or an external display
  identity mismatch).

## Files
- work/ring61.raw, work/ring61-full.txt (stale-header truncation, kept as
  the bug's evidence), work/ring61-true.txt (full decode).
- tools/pra_readlog.sh (the stale-header fix).
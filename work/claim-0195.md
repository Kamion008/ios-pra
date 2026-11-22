# CLAIM: 0195 (the T19 touch self-test + worker heartbeat)

author: Buffy (Freebuff session 2026-11-21). The patch is emitted by
work/gen0195.py from the reconstructed post-0194 base:
work/ci190/post0189 + 0190 for pra_touch.c, work/ci193/pre0193 +
0193 + 0194 for SweetHID.cpp, and work/ci193/pre0193 (already
post-0191/0192) for IOHIDEventServiceUserClient.cpp. Three-way verify
PASS + structural assertions (evidence 4). Base evidence: T18 ring59
(evidence 1), the T18 image disassembly (evidence 2), and the 0195
patch itself (evidence 3).

K1 (VERIFIED): T18 DID NOT EXERCISE 0194. ring59 (work/ring59-own.txt,
2,104 lines) has the probe lines `app mode confirmed, input reg 0x3
max_input=254` and `probe done, 10 ms poll worker started`, but:
```
$ python3 -c '...count...'
   0  SWEET HID: touch
   0  PRA touch: hid inject
   2  PRA touch: irq lo/hi
   2  reports=0
```
The only two 10 s samples both say `reports=0 errs=0 corrupt=0`.
No touch event ever reached `SweetHIDTouch::touch()`, so the 0194 clamp
was never called. The boot reached SpringBoard (SpringBoard AKS lines in
ring59); this is not a boot failure.

K2 (VERIFIED): THE FLASHED IMAGE CONTAINS 0194. The decompressed boot
payload contains the string `SWEET HID: panel arm A5XELTE 1080x1920`,
and the T18 kernel's `SweetHIDTouch::start()` disassembly stores the
const pair `(1080,1920)` into `[x19,#0xc0]` (fPanelW/fPanelH) before the
0194 marker; `touch()` loads `[x19,#0xc0]/[x19,#0xc4]` for the clamp.
Evidence 2 has the exact instructions and the const bytes. This proves
the image contains 0194; it does NOT prove start() ran at runtime, and
the missing touch call means the clamp's runtime behavior is still
untested.

K3 (VERIFIED, source-level): THE SELF-TEST BYPASSES pra_touch AND THE IC.
With `pratouchselftest=1`, SweetHIDTouch::start() sets
`gSweetTouchSelfTest = true`. IOHIDEventServiceUserClient's
`clientMemoryForType()` calls `sweet_hid_touch_selftest(_owner)` after
the queue map returns and only when `_state == kUserClientStateOpen`.
The callee checks `_owner == gSweetTouch`, clears the one-shot flag, and
calls:
```
gSweetTouch->touch(0, true, 2000, 3000);
gSweetTouch->touch(0, false, 2000, 3000);
```
The raw point is deliberately out of bounds: 0194's clamp must turn it
into 1079,1919. (An in-bounds 550,1911 would print unchanged even with a
broken clamp, so it would not test the clamp.) T19's ring must contain
`SWEET HID: selftest raw 2000,3000` followed by `SWEET HID: touch 0
down/up at 1079,1919` if 0194 is effective; -1,-1 means zeroed dims, and
an unclamped 2000,3000 means the clamp was bypassed. The call happens
after the user client is open, so the event callback's `_state ==
kUserClientStateOpen` guard passes.

K4 (VERIFIED, source-level): THE HEARTBEAT DISTINGUISHES THE TWO T18
CAUSES. With `pratouchdbg=1`, the worker prints every 10 s sample (not
only changed counters) and adds `reads` (input reads attempted) and
`last_len` (the last length-word result). `pra_touch_input_read()`
normalizes a raw length of 0 or 2 to `*lenp = 0` ("nothing pending"), so
`last_len=0` means no report. A continuing heartbeat proves the worker
loop reached the print; `reads` is incremented only inside
`if (do_read && backoff == 0)` and after `pra_touch_input_read()`, so a
heartbeat with a frozen `reads` means the read gate (`pra_live &&
input_reg != 0 && backoff == 0`) did not fire, not that the loop is
blocked. `reads` climbing with `last_len=0` proves the worker is polling
a silent IC.

K5 (INFERRED): T18's zero report count has two live explanations: the
worker stopped/blocked after its first two samples, or every input read
returned "nothing pending" from the IC. The ring cannot distinguish
them because T18 had no heartbeat. T19's `reads/last_len` lines decide.

K6 (UNKNOWN): whether the synthetic touch reaches backboardd's queue
and the UI. The out-of-bounds selftest proves the clamp and the queue enqueue; it does
not prove SpringBoard reacts. If the selftest prints 550,1911 and the
queue stats advance but the UI stays inert, the next rung is userland
routing, not the touch driver.

FALSIFIER: T19 ring60 has no `SWEET HID: selftest` line = the map hook
or boot arg did not run; `SWEET HID: touch ... at -1,-1` after the
selftest marker = 0194 is not effective at runtime; an unclamped
2000,3000 = the clamp was bypassed; heartbeat lines stop or `reads`
freezes = worker died/blocked; `reads` climbs with `last_len=0` = the IC
is silent; selftest clamped to 1079,1919 + queue enqueue = the clamp is
fixed and the remaining question is userland routing.

========================================================================
T19 OUTCOME (ring61, decoded 2026-11-22) — THE FALSIFIER FIRED AND HIT
========================================================================

K7 (VERIFIED): THE 0194 CLAMP IS EFFECTIVE AT RUNTIME. ring61 (the full
216,150-B text, not the stale-header 35,665-B readout) lines 1001-1007:
`SWEET HID: SweetHIDTouch open ...`, `queue mapped by SweetHIDTouch`,
`SWEET HID: selftest raw 2000,3000`, `SWEET HID: touch 0 down at
1079,1919 edge`, `SWEET HID: touch 0 up at 1079,1919 edge`. The
out-of-bounds point was clamped to (1080-1, 1920-1) exactly as
predicted; -1,-1 and unclamped 2000,3000 both absent.

K8 (VERIFIED): THE WHOLE KERNEL TOUCH HALF WORKS. 84 telemetry samples
over 84,000 x 10 ms polls = 840 s = 14.0 min (python3:
84000*0.010=840); final `reports=579 errs=16 corrupt=0 reads=82451`
(err rate 16/579 = 2.8%); 36 `SWEET HID: touch` transitions (18/18
down/up) ALL in-bounds (min (168,907), max (1079,1919) on 1080x1920);
`PRA touch: hid inject slot=0 down x=168 y=907` with real coords;
`-1,-1` appears nowhere.

K9 (VERIFIED): DELIVERY TO THE QUEUE AND DRAIN, AGAIN. `queue mapped`
x2, `queue notify armed` x2, `queue stats` 15 lines, last
`enq=514 drop=0 type=11 head=9600 tail=9600`. 514 events x 236 B =
121,304 B = 118.5 KiB through the 16 KiB queue = 7.4x overflow with
drop=0 and head==tail at every sample (the T16 drain method).

K10 (VERIFIED, user report): THE UI DID NOT REACT. The user confirms
(2026-11-22): many taps/swipes over the run; the iOS UI showed NO
reaction at all. The blocker is confirmed downstream of the kernel:
backboardd drains the queue but its HIDEventSystem does not route the
digitizer events to SpringBoard's gesture recognizers. The SweetHID
service and event code is identical to the donor path (A5XELTE 0123
device-verified touch; herolte 0216 working touch), so a kernel event-
format difference is the low-probability branch.

K11 (INFERRED): THE LOCK-SCREEN HYPOTHESIS — every PRA touch test so
far (T13-T19) was observed on the LOCK SCREEN (the empty
com.apple.SetupDone.plist bypass), while the working donor evidence was
taken on the HOME SCREEN after Setup was marked complete (the sweet
donor v14 purplebuddy data_ark path; A5 0123 / herolte 0216). An inert
lock screen with a working delivery path is not excluded. The clean
discriminator: a root image that boots past the lock screen (or a
home-button press to reach the home screen), then touch.

EVIDENCE: work/evidence-ring61.md. Ring: work/ring61-true.txt
(216,150 B, 3,703 lines). The stale-header truncation bug that hid the
real tail is fixed in tools/pra_readlog.sh.

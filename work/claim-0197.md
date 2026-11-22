# CLAIM: 0197 (the T20 outcome — the swipe is delivered and not accepted)

Author: workhorse session 2026-11-22 (after T20). NOT a patch claim: this
file records what boot T20 (the 0196 synthetic bottom-edge unlock swipe)
proved, refuted and left open, from the decoded ring `work/ring62-full.txt`
(sha256 6f184b482092ea4dd2548a6c297b3760580cda696a43369f944f6a5c9cb34b35,
202,057 B). Companion: `work/evidence-0197.md` (captured commands and
outputs) and `work/ring62-decode.md` (the full factual tabulation).
Line numbers are LF-based lines of `work/ring62-full.txt`.

K1 (VERIFIED): THE GESTURE FIRED 3/3, EXACTLY AS DESIGNED. Run 1: 1598
`SWEET HID: swipe 1 start (interval 420 s) at 540,1914`, 1599 `touch 0 down
at 540,1914 edge`, `move 1/8..8/8` at 1604-1616 with y = 1764,1614,1464,
1314,1164,1014,864,714, 1617 `touch 0 up at 540,714 edge`, 1618 `release at
540,714`. Runs 2 and 3 are the same line sets at 2047-2062 and 2481-2495;
2496 is `swipe selftest done`. 31 `SWEET HID: swipe` lines total. The
control ran FIRST, before any swipe: 980-983 `selftest raw 2000,3000` ->
`touch 0 down/up at 1079,1919 edge`, i.e. 0194's clamp live on a second,
independent boot.

K2 (VERIFIED): ONE EVENT PER touch() CALL. `queue stats` reads enq 0 -> 2
-> 12 -> 22 (samples at 982, 1601, 2050, 2484). The per-run delta is
exactly +10 for 10 touch() calls (down + 8 moves + up), and the pre-swipe
+2 is the selftest's down/up pair. So the swipe's serialization is one 236
B event per contact sample, with no coalescing and no loss.

K3 (VERIFIED): DELIVERY HELD. `head==tail` at all 4 samples (0/0, 480/480,
2880/2880, 5280/5280), `drop=0` at all 4, `event size=236
sender=0x100000131`. The first pair is trivially equal (0/0 during the
selftest) and proves nothing, so the drain evidence is samples 2-4. The
queue was empty every time it could be sampled, so backboardd dequeued
every event the swipe produced. This reproduces T16's drain proof on a
third boot with a synthetic source.

K4 (VERIFIED): NOTHING ACCEPTED IT. SpringBoard's AppleKeyStore calls to
selector 9 and selector 12 are ZERO in ring62 — identical to the ring61
baseline (both 0), across 849 AKS lines in ring62 vs 966 in ring61.
`sel 8` still returns 0xe00002c7 (Unsupported) x4, the same background
churn T16 exonerated. The user reports the lock screen unchanged with no
apparent new frames (hedged "it looks like"); that is a user visual
report, so the screen half of this claim is INFERRED, not VERIFIED.

K5 (VERIFIED, and it is a CONFOUND, not a result): T20 RAN WITHOUT THE
TOUCH IC. The cmdline the kernel received (`work/ring62-full.txt:233`,
475 B, byte-identical to `out/pra-xnu.img`'s payload at 0x800) ends
`... pratouchswipe=420 pratouchselftest=1 pratouchdbg=1` and contains
`pratouch=1` ZERO times and `pratouchreset=1` ZERO times; T19's 484 B
cmdline (ring61-true.txt:260) had both. The ring agrees: 0 `PRA touch`
lines, 0 `app mode confirmed`, 0 `reports=` (ring61: 104, 1, 84). The
0172 probe therefore never ran: no i2c scan, no descriptor read, no 10 ms
poll. Consequence: the user's own taps during T20 produced nothing BY
CONSTRUCTION, and only the 3 synthetic swipes are evidence from this
boot. The swipe still fired because 0196 arms its timer unconditionally
in `SweetHIDTouch::start()`; `pratouch` is parsed only in the 0172 probe
(`xnu/patches/0172-pra-touch-probe.patch:886`).

K6 (VERIFIED): THE QUEUE PATH DOES NOT DEPEND ON THE IC'S STATE. With the
IC never brought up (K5), the events were still constructed, enqueued and
drained exactly as in T19. So T20's delivery half is a clean, isolated
measurement of the SweetHID touch event path — and the acceptance half is
too, because the only digitizer source in the boot was the synthetic
gesture.

K7 (VERIFIED, with one INFERRED step): THE SENDERID IS NOT A SIGNAL.
`0x100000131` in ring62 is the same value ring61 logged on 17 lines.
T16's `0x100000126` differs by 11 (python3: 4294967601 - 4294967590 =
11). Measured: same as ring61, different from ring57. INFERRED (not
measured): the difference tracks per-boot registration order.

K8 (VERIFIED): SPRINGBOARD WAS NOT STALLED. The lock screen was presented
before swipe 1 (`display on` 1110, `backboardd create id 2` 1125, `swap
1/2/3` at 1135/1143/1191, `SpringBoard sel 40` 1508), and after swipe 1
SpringBoard created five more surfaces (ids 4-6 at 2291-2294, ids 7-9 at
2431-2433). SpringBoard's surface pipeline therefore keeps working across
the swipe window, which removes "the UI process wedged" as the simplest
explanation of the silence. Corollary, also VERIFIED: the second `display
on` (2171, with `backboardd sel 79 in 2/0 out 0/40` 2172 and `swap 6`
2173) is NOT a wake caused by swipe 2 - the touch-free ring61 carries the
identical triple at 2533-2535, so it is a recurring boot pattern.

K9 (UNKNOWN, unchanged): WHICH DOWNSTREAM BRANCH IS LIVE. (i) the gesture
is rejected at the HID layer, (ii) backboardd's HIDEventSystem drops it
before dispatch, (iii) backboardd dispatches and SpringBoard never
accepts. A negative swipe does not separate them, and T20 did not try to.

K10 (INFERRED, the next test): A NON-DIGITIZER CONTROL SEPARATES (i)/(ii)
FROM (iii). SweetHIDButtons' queue is mapped and armed by backboardd in
the same boots (`queue mapped` / `notify armed by SweetHIDButtons` x2 in
both rings), so a synthetic power (consumer page) key down+up through
that service exercises backboardd -> SpringBoard IPC with an event class
the UI cannot ignore. A visible screen-off/on proves the IPC path and
puts the defect on the digitizer event shape or the digitizer client;
total silence makes the failure generic to this port. T21 = that
control, with `pratouch=1 pratouchreset=1` restored (killing K5's
confound) and the sampler aimed at SpringBoard for the first time.

K11 (VERIFIED - the 4 B/event "accounting gap" is RESOLVED, it was my own
missing header term): `head` advances 240 B per event while the serialized
event is 236 B, because every queue entry carries a 4 B header. Source:
`xnu-src/iokit/IOKit/IODataQueueShared.h:79`
`#define DATA_QUEUE_ENTRY_HEADER_SIZE (sizeof(IODataQueueEntry) - 4)`, with
the struct at :43-46 being `{ UInt32 size; UInt8 data[4]; }` (sizeof 8, so
the header is 4); the enqueue path is
`IOHIDEventServiceQueue::enqueueEvent` -> `dataSize =
ALIGNED_DATA_SIZE(eventSize, 4)`, `entrySize = dataSize +
DATA_QUEUE_ENTRY_HEADER_SIZE` (IOHIDEventServiceQueue.cpp:90-106).
```
$ python3 -c "print('236 + 4 =', 236+4); print('ALIGNED(236,4) =', (236+3)//4*4); print('5280/240 =', 5280/240)"
236 + 4 = 240
ALIGNED(236,4) = 236
5280/240 = 22.0
```
So 236 B payload + 4 B header = the observed 240 B stride and 5280 B for
22 events. Nothing about the delivery verdict changes; the earlier record
simply lacked the header term.

K12 (VERIFIED, source-read - T21 mechanics a future session must not
re-derive): (a) the key path is UNGATED by hardware: `SweetHIDButtons::
key()` builds `IOHIDEvent::keyboardEvent(..., kHIDPage_Consumer, usage,
down)` and calls `dispatchEvent` - no finger slot, no latch, no PMIC
dependency; the registered instance is reachable as `gSweetButtons`, and
the C wrapper `sweet_hid_key()` already maps index 0 to
`kHIDUsage_Csmr_Power` (0x30). (b) A press should log `SWEET HID: key 0x30
down (1 clients)` plus `SWEET HID: event size=60`, and a down+up pair costs
128 B of the 16,384 B queue (python3: 60 + 4 header = 64 per entry, x2).
(c) The sampler takes a COMMA LIST and its built-in default is ALREADY
"SpringBoard,backboardd"; the PRA cmdline overrides it with
`sweetsample=Setup`, a process that never runs - so aiming it needs NO
patch, only dropping that arg. Match is exact, case-sensitive `p_comm`
equality truncated to 16 chars, so both names fit; first sample at 90 s,
then every 120 s, up to 90 samples. That is why no ring has ever contained
a SpringBoard sample: the target list was always "Setup".

Not claimed: that touch works, that touch is broken for a specific
reason, that any frame count is known (the 0046 swap log is capped at 16
and skips masked surfaces - ring62 printed 8 lines with counters
1,2,3,6,7,8,14,15, so at most one more line could ever have appeared),
or that T20's boot args were correct.

NUMBERING: this file is a DECODE record and carries no patch, so it has no
three-way verify to show. The next kernel patch (the T21 non-digitizer
control) takes 0198; do not create a second 0197 pair.

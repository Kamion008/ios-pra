# CLAIM: 0198 (the T21 power-key control — a non-digitizer HID event)

Author: research sub-agent session 2026-11-22 (T21 prep, pre-boot). Claim for the landed patch
`xnu/patches/0198-pra-power-key-control.patch` (commit 89d95c6, 136 lines,
`iokit/Kernel/arm/hid/SweetHID.cpp` only, index-stripped — no `diff --git`/`index` lines — so GNU
patch is the primary leg). Three-way verify in a scratch tree seeded from
`work/0198/SweetHID-pre0198.cpp`: GNU `patch -p1 --fuzz=0 --dry-run` rc=0, real apply rc=0, `cmp`
against `work/0198/SweetHID-post0198.cpp` rc=0, `git apply --check` rc=0 — and for THIS patch that
last leg is discriminating, which is not true in general: re-run on an already-applied tree, git
2.56.1 returns rc=1 (`error: ... patch does not apply`) and GNU patch 2.8.1 answers `Reversed (or
previously applied) patch detected! ... 4 out of 4 hunks ignored` (rc=1), so rc=0 cannot be a skip
here. AGENTS.md:44-49's skip-detect warning is a general rule that did not bite this diff (both
re-runs are pasted in `work/evidence-0198.md` §1). awk recount: 4 hunks, adds 8+12+20+47 = 87,
deletes 0. Companion `work/evidence-0198.md`; base evidence claim-0197 (T20 and its three live
branches), `work/ring62-decode.md`, `HANDOFF_2026-11-22b.md:163-233`.

PURPOSE (VERIFIED problem, INFERRED answer). T20 proved the synthetic digitizer swipe was
enqueued and drained 3/3 with nothing accepted (claim-0197 K1-K4) and left three branches that a
digitizer-only result cannot separate (claim-0197 K9): (i) the digitizer event SHAPE is rejected at
the HID layer, (ii) backboardd's HIDEventSystem drops it before dispatch, (iii) dispatch happens
and SpringBoard never accepts. All three produce the same silence; one non-digitizer event through
the SAME service, queue and backboardd client splits them for the price of one boot — no new
driver, no IC, no userland change.

K1 (VERIFIED, source-level): DECISIVE IN ONE DIRECTION ONLY. `key()` builds a consumer-page
keyboard event and dispatches it into the queue backboardd already drains, so an ACCEPTED key
proves the shared HID -> queue -> backboardd -> userland path works for a non-digitizer class and
narrows the digitizer defect to (i) or a digitizer-only dispatch drop; a REJECTED key carries no
matching force (K8).

K2 (VERIFIED, source-level): NO FINGER SLOT, NO LATCH, NO PMIC. `work/0198/SweetHID-pre0198.cpp`,
quoted (key() is :428-438):
```
430		IOHIDEvent *event = IOHIDEvent::keyboardEvent(mach_absolute_time(), kHIDPage_Consumer, usage, down);
433		IOLog("SWEET HID: key 0x%x %s (%u clients)\n", (unsigned)usage, down ? "down" : "up",
435		dispatchEvent(event);
```
Inputs are the usage, the boolean and the timestamp only. The wrapper's table (pre:670-680) maps
0/1/2/3 to `kHIDUsage_Csmr_Power` 0x30, `VolumeIncrement` 0xE9, `VolumeDecrement` 0xEA, `Menu`
0x40, and `IOHIDUsageTables.h` agrees: `:991 kHIDUsage_Csmr_Power = 0x30, /* On/Off Control */`,
`:1114 kHIDUsage_Csmr_VolumeIncrement = 0xE9`, `:1115 ...VolumeDecrement = 0xEA`,
`:999 kHIDUsage_Csmr_Menu = 0x40` (page = Consumer, `:980 ConsumerControl = 0x01`). `fDown[]`/
`fEdge[]` are `SweetHIDTouch` members (pre:393-394) in the other class; the PMIC path lives only in
`sweet_keys.c` (PM6150L, guard `#if defined(ARM64_BOARD_CONFIG_SWEET)` at :7) and is never entered
on PRA. Every digitizer-specific mechanism is absent.

K3 (VERIFIED, source + arithmetic): THE TEST COSTS 128 B OF 16,384. A key event serializes to
60 B (claim-0197 K12, source-read — INFERRED here, never measured on this port) and each queue
entry adds the 4 B `IODataQueueEntry` header (claim-0197 K11, IODataQueueShared.h:79), so an entry
is 64 B and a down+up pair 128 B:
```
$ python3 -c 'print(2*(60+4), 16384//(2*(60+4)), 2*(60+4)/16384, 64*4)'
128 128 0.0078125 256
```
0.78 % of the queue, 128 pairs to fill it, and `head` advances 64 B per key event — so
`head == 64*enq` is the T21 drain test, not ring62's 240 B stride. ring63 confirms the stride on
real data: `enq=2 drop=0 type=3 head=128 tail=128` (:1626).

K4 (VERIFIED, source + ring62): THE CLIENT COUNT IS THE ARMING HEALTH CHECK. The count is read
before dispatch (pre:433-435) and `dispatchEvent` iterates the same array (pre:206-228), so a
press with 0 clients logs a line and then discards the event. The one client is backboardd's user
client: ring62:996 `SweetHIDButtons open by IOHIDEventServiceUserClient -> 1`, :997 `queue mapped
by SweetHIDButtons`, :1002 notify armed (`handleOpen` appends to `_clients`, pre:119-133, 141-164).
So `(1 clients)` is expected and `(0 clients)` means the press beat backboardd's queue map — a
boot-timing artifact, not a delivery verdict. `armReport` prints the same count from its own
timer (post:485-492) — 30 s after `start()` in 0198/0199, `prapowerkey` seconds after **0200** —
i.e. the steady state, not the press instant (and see K5: in 0198/0199 it never reached the ring at
all).

K5 (INFERRED from the source, then CORRECTED BY THE BOOT): THE EXPECTED RING SIGNATURE — AND THE ARM
LINE NEVER LANDED. `prapowerkey=N` arms one timer in `start()` behind explicit `fKeyErr` codes
(post:441-456: 2 = no timer, 3 = `addEventSource` failed, 4 = `setTimeoutMS` failed) plus an
unconditional report timer (post:457-460). The report exists because `start()` runs before the pralog
ring is alive — VERIFIED: `buttons registered`, `selftest armed` and `panel arm` have 0 hits in
ring61, ring62 and ring63, so `start()`'s own IOLog never lands — and because 0196's block logged
nothing on failure, which is exactly what made T20's "no line" ambiguous (claim-0196.md:159-162: the
timer never fired "is also what a failed addEventSource or an unparsed/zero pratouchswipe looks
like"); `err=` removes the ambiguity. **Then the report repeated the very bug it was added to
catch.** 0198 armed it 30 s after `start()` (0199 kept the 30 s, 0200 changed it), and `start()`
sits ~5 s into the boot (INFERRED — 0200's estimate; nothing in the ring dates it), so the report
fired at ~+35 s, still inside the window where IOLog does not reach the ring. ring63 came from the
0198-only T21a image — its arm format has no 0199 `every=%u` field (`work/evidence-0198.md` §3) — so
what was armed there was precisely the 30 s timer. ring63 proves it was never written:
```
$ grep -c "arm secs" work/ring63-full.txt; echo "grep rc=$?"; strings -a work/ring63.raw | grep -c "arm secs"; echo "strings|grep rc=$?"
0
grep rc=1
0
strings|grep rc=1
```
Zero in the text dump AND zero in the raw image, so it was never emitted, not truncated. The same
boot DID record the key lines, and that is what makes this a TIMING failure rather than a timer
failure: both timers are created and added by the same code pattern in `start()`, the one due at
+300 s logged (:1121-:1126), the one due at +35 s left nothing — the difference is when the ring
became writable. What the failure
leaves OPEN: `fKeyErr` 2/3/4 stay unobservable, so a boot with no key lines remains ambiguous exactly
as in T20 (dead timer vs. unparsed arg vs. ring too early). Patch **0200**
(`xnu/patches/0200-pra-power-key-arm-report.patch`, commit aa18a99, awk recounts 2 hunks, 12 added /
2 removed) closes it: the report timer now takes `(fKeySecs ? fKeySecs : SWEET_KEY_REPORT_S)`
(0200:43), so with `prapowerkey=N` it is due at the same N seconds as the first press — the arm line
lands WITH the press instead of depending on a guess about when pralog comes up; and `armed=` is
redefined as "allocated AND `err == 0`" (0200:49-52), so `err=3 armed=1` can no longer read as
healthy. Note on 0200's own wording (VERIFIED against the post file, and it contradicts the commit
message): the code arms the KEY timer first (`work/0200/SweetHID-post0200.cpp:463`) and the report
second (:482) with the SAME timeout, so "the report timer is armed first, therefore it fires first"
is not what the code does. What is guaranteed is that both are due at N s, i.e. the arm line lands in
the same work-loop neighbourhood as `powerkey 1 down`; which of the two prints first is UNKNOWN and
the reading must not depend on it. The arm line is a ring64 expectation, NOT a ring63 observation.
THE REAL ring63 SEQUENCE (VERIFIED, quoted from `work/ring63-full.txt`):
```
1121: SWEET HID: powerkey 1 down (interval 300 s) usage 0x30
1122: SWEET HID: key 0x30 down (1 clients)
1123: SWEET HID: event size=60 sender=0x100000127
1124: SWEET HID: queue stats enq=0 drop=0 type=0 head=0 tail=0
1125: SWEET HID: key 0x30 up (1 clients)
1126: SWEET HID: powerkey 1 up
1623: SWEET HID: powerkey 2 down (interval 300 s) usage 0xe9
1624: SWEET HID: key 0xe9 down (1 clients)
1625: SWEET HID: event size=60 sender=0x100000127
1626: SWEET HID: queue stats enq=2 drop=0 type=3 head=128 tail=128
1627: SWEET HID: key 0xe9 up (1 clients)
1628: SWEET HID: powerkey 2 up
1629: SWEET HID: powerkey done
```
Three source facts behind those numbers (VERIFIED): `event size=` is a `printf` gated at 1920000
ticks (pre:216-221), so one line covers a whole 100 ms press — one per press, not per event;
`queue stats` is written inside `enqueueEventGated` BEFORE the current event is counted (the
`head=`/`tail=` fields are **0192-pra-hid-drain-telemetry.patch:88-90**; 0191's printf at 0191:93 is
`enq=%llu drop=%u type=%u` only), and its `head`/`tail` pair is the drain state (`head == tail` = the
queue is empty again); and it is a PER-SERVICE line, because each service's user client owns its own
queue and its own counters (`kQueueSizeMax` = 16384, IOHIDEventServiceUserClient.cpp:38, :265;
`_queue`/`_eventCount`/`_droppedEventCount` are IOHIDEventServiceUserClient members, .h:59-67) — so
key events are counted in SweetHIDButtons' OWN 16 KiB queue, never in the digitizer's. That is why
:1124 is all zeros (the first print for THAT queue, taken before the down event is counted) and why
:1626 reads `enq=2 type=3 head=128` (the pair counted, last type keyboard, and drained): one pair =
2 events = 2*(60+4) = 128 B = `head`, i.e. 64 B per event:
```
$ python3 -c 'print(2*(60+4), 128//64, 64*2)'
128 2 128
```
The `queue stats` line names no service, so which queue a line belongs to is settled by two other
facts: there are TWO `queue mapped by` lines, and every event carries the senderID of the service
that dispatched it (`event->setSenderID(getRegistryEntryID())`, :210) —
```
$ grep -n "queue mapped by\|SweetHIDButtons open\|sender=" work/ring63-full.txt
1017:SWEET HID: queue mapped by SweetHIDTouch
1020:SWEET HID: event size=236 sender=0x100000128
1030:SWEET HID: SweetHIDButtons open by IOHIDEventServiceUserClient -> 1
1031:SWEET HID: queue mapped by SweetHIDButtons
1123:SWEET HID: event size=60 sender=0x100000127
1625:SWEET HID: event size=60 sender=0x100000127
2537:SWEET HID: event size=236 sender=0x100000128
```
`0x100000127` rides every 60 B key event (:1123, :1625) and `0x100000128` every 236 B digitizer event
(:1020, :2537), so the 60 B / `type=3` / 64 B-stride lines belong to the button service. Corollary:
the `type=11 head=480 tail=480` lines from :2538 on are the TOUCH queue and say nothing about the key
pair — an earlier draft of this claim quoted `2/11/480` as the expected key-pair stat and told the
reader to "subtract the selftest's +2", and both were wrong for exactly this reason.
TIMING, CORRECTED BY THE FIRST BOOT (VERIFIED on the ring; the "10 min" is the user's heuristic, not
a measurement): T21a was packaged with N=300, so both pairs fired ~5 min after power-on. The ring
places them against the DISPLAY path rather than against a lock screen: `SWEET FB: display on` is at
:1212 and swaps 1-5 at :1241/:1248/:1254/:1353/:1393 — i.e. BETWEEN the two pairs. So only pair 1
(:1121-:1126, the power press) is provably pre-UI; pair 2 (:1623-:1629, volume up) went into a
display that had already started presenting, and whether the lock screen was INTERACTIVE by then is
UNKNOWN (no ring evidence either way). The user's heuristic — this port needs AT LEAST 10 min to
reach a usable lock screen — is what makes T21a unusable for the T21 question: pair 1 is too early to
be seen and pair 2 is ambiguous. T21b re-packages the SAME kernel (no rebuild: the timing is a boot
arg, not code) with `prapowerkey=900` = 15 min (`work/0198/cmdline.txt`), comfortably outside the
heuristic: power pair 900.1 s, volume pair 1020.1 s, `done` 1020.2 s = 17 min:
```
$ python3 -c 'print(900.1, 900+120.1, 900+120.2, 900/60.0, 1020/60.0)'
900.1 1020.1 1020.2 15.0 17.0
```

K6 (INFERRED, the ladder ring63 is read against): (a) key lines + `enq` +2 per pair + `head == 64*enq`
+ drop=0 + a userland/display reaction = a non-digitizer HID event was accepted end to end; the
digitizer defect is shape- or client-specific. (b) The same enqueue/drain evidence and nothing
visible anywhere = branch 2 again, now proven non-digitizer-specific: the drop is at the queue ->
dispatch boundary for every event type. (c) No key lines, or `enq` never grows, or `(0 clients)`
persisting past the queue map = a patch or timer bug, not a finding — fix and reflash. (d)
`pratouch=1` in the cmdline with 0 `PRA touch` lines = the IC path regressed, a SEPARATE finding
from the key result. `pratouchselftest=1` spends its own +2 `enq` at queue-map time (claim-0197
K2), but that +2 lands in the TOUCH queue's counters, not the button queue's (K5), so a
button-queue `enq` delta is never inflated by the selftest — ring63's `enq=2` at :1626 is exactly
the key pair, nothing to subtract. Where ring63 lands on this ladder: the HID half of (a) is
SATISFIED — key lines, `enq` +2, `head == 64*enq`, `drop=0`, head==tail (drained) — but the UI half
is not observable: no user visual report is recorded for T21a (`work/boots.md`, T21a row) and, per
K7, the ring carries no event-attributable display signal, so (a) vs (b) for the KEY class stays
OPEN and is exactly the T21b question.

K7 (SOURCE VERIFIED, INTERPRETATION REVISED): `a5fb_keep_on=1` MAKES A REAL SLEEP NON-DESTRUCTIVE,
BUT THE RING CANNOT SHOW THAT THE KEY REACHED USERLAND.
`xnu-src/iokit/Kernel/arm/SweetFramebuffer.cpp:619-631`, quoted (the keep flag is parsed at :624):
```
619	case kSweetFBRequestPowerChange:
621			bool off = args->scalarInput[0] == 0;
628			if (off && have_keep && keep_on) {
629				IOLog("A5XELTE FB: display-off request ignored (keep_on)\n");
630				break;
```
`a5fb_keep_on=1` is in the default cmdline (tools/pra_package.sh:54) and in the cmdline T20
received (ring62-full.txt:187); defaults are never pruned (AGENTS.md:33-40). So a sleep request will
NOT darken the screen. What that does NOT buy is the positive this claim used to claim: the
`A5XELTE FB: display-off request ignored (keep_on)` line is BASELINE NOISE. It appears 0-3 times per
boot on boots with NO key event anywhere in them, so its presence is not attributable to our press:
```
$ for f in ring52-fresh ring53-fresh ring54-fresh ring55-full ring56-full ring57-full ring58-full ring59-full ring61-true ring62-full ring63-full; do printf "%-14s %s\n" "$f" "$(grep -c 'display-off request ignored' work/$f.txt)"; done
ring52-fresh   2
ring53-fresh   3
ring54-fresh   2
ring55-full    2
ring56-full    1
ring57-full    2
ring58-full    2
ring59-full    1
ring61-true    2
ring62-full    2
ring63-full    2
```
(`work/ring61-full.txt` reads 0 only because it is the short 515-line pull.) ring34 already named it:
`work/ring34-notes.md:22` — `"A5XELTE FB: display-off request ignored (keep_on)" x2 — the idle
display-off IS ignored for the panel`, on a boot with no key event at all. Inside ring63 the two hits
are at :1782 and :2634, i.e. long before `powerkey 1 down` (:1121) and ~1000 lines after `powerkey
done` (:1629) — neither is adjacent to a press. So under the default `a5fb_keep_on=1` the ring
carries NO event-attributable display signal, and the positive for T21 is (i) the user's visual
report — the sleep attempt visibly ignored, or the volume HUD — or (ii) a baseline-count INCREASE
(3 where this boot had 1-2) landing temporally adjacent to a press, which is weak and must be quoted
as a count, not as "the line appeared". The keep_on arm still guarantees non-destructiveness if the
sleep request does fire (no screen-state risk); it just cannot be the evidence. The line does not
name the requester either (only the notification arm logs `proc_selfname`, :613-616); that identity
stays INFERRED as the userland display-sleep path.

K8 (INFERRED): A NEGATIVE IS WEAKER. iOS may not map our consumer usage to any action, a mapped
key may be accepted and then ignored by policy, and neither case is separable from a dead path by
silence. A silent T21 proves only "this usage value produced no visible action"; it does NOT prove
the non-digitizer dispatch path is dead. The second usage (volume up, post:507-508) is the hedge —
visible HUD, distinct code path — so silence on both is much stronger than silence on power alone,
and still weaker than any positive.

NOT PROVEN BY THIS PATCH: which of the three blocker branches is live for the DIGITIZER (a
positive only narrows it); whether SpringBoard's HID INPUT client is registered at all
(`clients=N` counts backboardd's `IOHIDEventServiceUserClient`, not SpringBoard's input session —
handoff:207-217 is still the only probe for that); any frame count (the 0046 swap log is capped at
16 entries and ring62 printed 8 with counters to 15); and anything about the touch IC, which needs
`pratouch=1 pratouchreset=1` restored in the same boot.

KNOWN WEAKNESSES IN THIS PATCH (not blockers, recorded rather than fixed): (a) `armReport()` and
`key()` read `_clients` OUTSIDE `_clientLock` (post:474, post:491) while `handleOpen`/`handleClose`
copy-on-write and RELEASE the old array (pre:150-162, pre:169-181), so a client close racing a press
can read a freed `OSArray`. The window is tiny (one close, at boot, vs. a press every 300 s) and
`key()`'s instance of it is the inherited pre-existing pattern (pre:433-434), but `armReport()` is
new in this patch, and the correct pattern is already in the same file — `dispatchEvent` snapshots
under the lock and retains (`post:211-214`). Not fixed here because it is a pre-existing
lock-discipline change and this patch is a diagnostic control. (b) `fKey` and `fArm` are never
released: `SweetHIDButtons` declares no `free()` (`grep -c "SweetHIDButtons::free"` = 0), so both
`IOTimerEventSource`s outlive the service. Harmless in practice — an expired `IOTimerEventSource`
disables itself, so after `powerkey done` (and after the one-shot arm report) nothing re-fires — but
it is a leak, not a clean shutdown. (c) the arm report is armed UNCONDITIONALLY (post:457-459 sits
outside the `prapowerkey` block), so a boot WITHOUT `prapowerkey` still gets one line. After 0200
that line fires 30 s after `start()` — the exact window that swallowed ring63's — so whether it
lands in the ring is UNKNOWN and must not be assumed either way; it costs one timer, not a wrong
verdict.

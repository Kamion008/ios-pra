# CLAIM: 0198 (the T21 power-key control — a non-digitizer HID event)

Author: research sub-agent session 2026-11-22 (T21 prep, pre-boot). Claim for the landed patch
`xnu/patches/0198-pra-power-key-control.patch` (commit 89d95c6, 136 lines,
`iokit/Kernel/arm/hid/SweetHID.cpp` only, index-stripped — no `diff --git`/`index` lines — so GNU
patch is the primary leg). Three-way verify in a scratch tree seeded from
`work/0198/SweetHID-pre0198.cpp`: GNU `patch -p1 --fuzz=0 --dry-run` rc=0, real apply rc=0, `cmp`
against `work/0198/SweetHID-post0198.cpp` rc=0, `git apply --check` rc=0 (recorded, NOT proof —
AGENTS.md:44-49: local git 2.56 skip-detects an already-applied patch at rc=0). awk recount: 4
hunks, adds 8+12+20+47 = 87, deletes 0. Companion `work/evidence-0198.md`; base evidence
claim-0197 (T20 and its three live branches), `work/ring62-decode.md`,
`HANDOFF_2026-11-22b.md:163-233`.

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
`head == 64*enq` is the T21 drain test, not ring62's 240 B stride.

K4 (VERIFIED, source + ring62): THE CLIENT COUNT IS THE ARMING HEALTH CHECK. The count is read
before dispatch (pre:433-435) and `dispatchEvent` iterates the same array (pre:206-228), so a
press with 0 clients logs a line and then discards the event. The one client is backboardd's user
client: ring62:996 `SweetHIDButtons open by IOHIDEventServiceUserClient -> 1`, :997 `queue mapped
by SweetHIDButtons`, :1002 notify armed (`handleOpen` appends to `_clients`, pre:119-133, 141-164).
So `(1 clients)` is expected and `(0 clients)` means the press beat backboardd's queue map — a
boot-timing artifact, not a delivery verdict. `armReport` prints the same count 30 s after
`start()` (post:485-492), i.e. the steady state, not the press instant.

K5 (INFERRED from the source): THE EXPECTED RING SIGNATURE. `prapowerkey=N` arms one timer in
`start()` behind explicit `fKeyErr` codes (post:441-456: 2 = no timer, 3 = `addEventSource`
failed, 4 = `setTimeoutMS` failed) plus an unconditional 30 s report (post:457-460). The arm line
is needed because `start()` runs before the pralog ring exists — VERIFIED: `buttons registered`,
`selftest armed` and `panel arm` have 0 hits in ring61 and ring62, so `start()`'s own IOLog never
lands — and because 0196's block logged nothing on failure, which is exactly what made T20's "no
line" ambiguous (claim-0196.md:159-162: the timer never fired "is also what a failed
addEventSource or an unparsed/zero pratouchswipe looks like"); `err=` removes the ambiguity.
Order:
```
30 s    SWEET HID: powerkey arm secs=N err=0 armed=1 clients=1
 N      SWEET HID: powerkey 1 down (interval N s) usage 0x30
 N      SWEET HID: key 0x30 down (1 clients)
 N      SWEET HID: event size=60 sender=0x...
 N      SWEET HID: queue stats enq=2 drop=0 type=11 head=480 tail=480
 N+0.1  SWEET HID: key 0x30 up (1 clients)
 N+0.1  SWEET HID: powerkey 1 up
 N+120.2  the same six lines with usage 0xe9 (volume up), then `powerkey done`
```
Two source facts (VERIFIED): `event size=` is a `printf` gated at 1920000 ticks (pre:216-221), so
one line covers a whole 100 ms press — one per press, not per event; `queue stats` is written
inside `enqueueEventGated` BEFORE the current event is counted
(0191-pra-hid-queue-telemetry.patch:90-95), so it shows pre-press `enq`/`head` and the previous
event's type (`3` = keyboard, IOHIDEventTypes.h:94; ring62 reads `11` = digitizer, :102) — hence
`2/11/480` when `pratouchselftest=1` ran first, `0/0/0` without it, and `head` up 128 B at press 2
if backboardd drained press 1. `N < 30` puts the arm line after the first press, so read the whole
ring. TIMING, CORRECTED BY THE FIRST BOOT: T21a was packaged with N=300 and the press
therefore landed ~5 min after power-on, BEFORE the lock screen exists - the user's rule is that
this port needs AT LEAST 10 min to reach it, so T21a cannot answer the T21 question (it is only
useful for reading where `start()` sits relative to backboardd's queue map, via its `(N clients)`
count). T21b re-packages the SAME kernel (no rebuild: the timing is a boot arg, not code) with
`prapowerkey=900` = 15 min (`work/0198/cmdline.txt`): power pair 900.1 s, volume pair 1020.1 s,
`done` 1020.2 s = 17 min:
```
$ python3 -c 'print(900.1, 900+120.1, 900+120.2, 900/60.0, 1020/60.0)'
900.1 1020.1 1020.2 15.0 17.0
```

K6 (INFERRED, the ladder to apply to ring63): (a) key lines + `enq` +2 per pair + `head == 64*enq`
+ drop=0 + a userland/display reaction = a non-digitizer HID event was accepted end to end; the
digitizer defect is shape- or client-specific. (b) The same enqueue/drain evidence and nothing
visible anywhere = branch 2 again, now proven non-digitizer-specific: the drop is at the queue ->
dispatch boundary for every event type. (c) No key lines, or `enq` never grows, or `(0 clients)`
persisting past the queue map = a patch or timer bug, not a finding — fix and reflash. (d)
`pratouch=1` in the cmdline with 0 `PRA touch` lines = the IC path regressed, a SEPARATE finding
from the key result. `pratouchselftest=1` spends its own +2 `enq` at queue-map time (claim-0197
K2); subtract it before calling a +2 a key pair.

K7 (VERIFIED, source + cmdline): `a5fb_keep_on=1` MAKES THE POSITIVE NON-DESTRUCTIVE.
`xnu-src/iokit/Kernel/arm/SweetFramebuffer.cpp:619-631`, quoted (the keep flag is parsed at :624):
```
619	case kSweetFBRequestPowerChange:
621			bool off = args->scalarInput[0] == 0;
628			if (off && have_keep && keep_on) {
629				IOLog("A5XELTE FB: display-off request ignored (keep_on)\n");
630				break;
```
`a5fb_keep_on=1` is in the default cmdline (tools/pra_package.sh:54) and in the cmdline T20
received (ring62-full.txt:187); defaults are never pruned (AGENTS.md:33-40). So the expected sleep
request will NOT darken the screen but WILL log `A5XELTE FB: display-off request ignored
(keep_on)` — a STRONGER positive than a real sleep: it proves the key reached userland and was
acted on, with no screen-state risk. It does not name the requester (only the notification arm logs
`proc_selfname`, :613-616); that identity is INFERRED as the userland display-sleep path.

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

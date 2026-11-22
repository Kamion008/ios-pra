# EVIDENCE — 0198: the T21 power-key control

Patch `xnu/patches/0198-pra-power-key-control.patch` (136 lines, SweetHID.cpp
only, index-stripped). Durable before/after: `work/0198/SweetHID-pre0198.cpp`
(708 lines) / `work/0198/SweetHID-post0198.cpp` (795 lines). Every block below
was re-run on 2026-11-22 in a fresh scratch tree under `/tmp` seeded from the
pre file (`cp` to `iokit/Kernel/arm/hid/SweetHID.cpp` plus the patch; for the
git leg a `git init` + one seed commit); pasted output is captured output.

## 1. Three-way verify

```
$ cd /tmp/t21v2 && patch -p1 --fuzz=0 --dry-run < 0198-pra-power-key-control.patch; echo "dry-run rc=$?"; patch -p1 --fuzz=0 < 0198-pra-power-key-control.patch; echo "apply rc=$?"; cmp iokit/Kernel/arm/hid/SweetHID.cpp /home/kamion008/Ai/ios/ios-pra/work/0198/SweetHID-post0198.cpp; echo "cmp rc=$?"
checking file iokit/Kernel/arm/hid/SweetHID.cpp
dry-run rc=0
patching file iokit/Kernel/arm/hid/SweetHID.cpp
apply rc=0
cmp rc=0
$ cd /tmp/t21g2 && git apply --check -p1 0198-pra-power-key-control.patch; echo "check rc=$?"; git apply -p1 0198-pra-power-key-control.patch; echo "apply rc=$?"; cmp iokit/Kernel/arm/hid/SweetHID.cpp /home/kamion008/Ai/ios/ios-pra/work/0198/SweetHID-post0198.cpp; echo "cmp rc=$?"
check rc=0
apply rc=0
cmp rc=0
```
`git apply --check` is recorded, and for THIS patch it is a discriminating pass,
not a skip: on a tree where 0198 is already applied, the same command fails
loudly. Re-run 2026-11-22 in `/tmp/v0198rev` (a `git init` tree whose one commit
seeds `work/0198/SweetHID-pre0198.cpp`), after the clean-tree pass above:
```
$ git --version; patch --version | head -1
git version 2.56.1
GNU patch 2.8.1
$ cd /tmp/v0198rev && git apply --check -p1 /home/kamion008/Ai/ios/ios-pra/xnu/patches/0198-pra-power-key-control.patch; echo "git check already-applied rc=$?"
error: patch failed: iokit/Kernel/arm/hid/SweetHID.cpp:343
error: iokit/Kernel/arm/hid/SweetHID.cpp: patch does not apply
git check already-applied rc=1
$ patch -p1 --fuzz=0 --dry-run < /home/kamion008/Ai/ios/ios-pra/xnu/patches/0198-pra-power-key-control.patch; echo "gnu dry-run already-applied rc=$?"
checking file iokit/Kernel/arm/hid/SweetHID.cpp
Reversed (or previously applied) patch detected!  Assume -R? [n] 
Apply anyway? [n] 
Skipping patch.
4 out of 4 hunks ignored
gnu dry-run already-applied rc=1
```
So AGENTS.md:44-49's skip-detect warning (`git apply --check` passing on an
already-applied tree) is a REAL general rule that did NOT bite this diff: both
legs return rc=1 with a diagnostic when the patch is already there, which means
the rc=0 recorded above really did apply against a clean tree. Both versions of
the GNU dry run, the real apply and the byte compare stay the primary legs; the
`cmp`s compare against the same durable post file, which is what makes the legs
byte-level.

## 2. Diff recount (awk over the patch)

```
$ awk '/^@@/{if(h)printf "hunk %d %s old=%d new=%d ctx=%d add=%d del=%d ok=%d\n",++n,h,oc,nc,c,a,d,(c+d==oc&&c+a==nc); h=$2" "$3; oc=substr($2,index($2,",")+1)+0; nc=substr($3,index($3,",")+1)+0; c=a=d=0; next} h&&/^ /{c++} h&&/^\+/{a++} h&&/^-/{d++} END{printf "hunk %d %s old=%d new=%d ctx=%d add=%d del=%d ok=%d\n",++n,h,oc,nc,c,a,d,(c+d==oc&&c+a==nc)}' xnu/patches/0198-pra-power-key-control.patch
hunk 1 -343,9 +343,17 old=9 new=17 ctx=9 add=8 del=0 ok=1
hunk 2 -364,6 +372,18 old=6 new=18 ctx=6 add=12 del=0 ok=1
hunk 3 -418,6 +438,26 old=6 new=26 ctx=6 add=20 del=0 ok=1
hunk 4 -437,6 +477,53 old=6 new=53 ctx=6 add=47 del=0 ok=1
```
Adds 8+12+20+47 = 87, deletes 0; every `ctx+del==old` and `ctx+add==new` holds,
so the hunk headers agree with their bodies. A naive `/^-/` count adds one false
delete (the `--- a/...` header).

## 3. Workflow marker assert, with context

```
$ sed -n '323,326p' .github/workflows/xnu.yml; grep -n "0198" .github/workflows/xnu.yml
          strings -a "$kernel" | grep -F 'SWEET HID: swipe' >/dev/null
          # 0198 non-digitizer power-key control guard: the delayed consumer
          # key pair and its arm report are present in the kernel.
          strings -a "$kernel" | grep -F 'SWEET HID: powerkey' >/dev/null
324:          # 0198 non-digitizer power-key control guard: the delayed consumer
```
`SWEET HID: powerkey` occurs 4x in the post file (post:489, 509, 519, 521), so
`strings -a` finds it in any kernel built with the patch.

STEP ATTRIBUTION, CORRECTED: the marker asserts are NOT in the Build step. They
run in the step named "Verify PRA preemption diagnostics are linked"
(xnu.yml:188, body 188-343; the 0198 assert is `:326`, the 0199
`powerkey arm secs=` assert `:329`), while "Build" is xnu.yml:91-151 and ends
with the skip detector at `:150`. Evidence, the actual greps of the workflow:
```
$ grep -n "name: Build\|name: Verify PRA preemption diagnostics are linked\|name: Check for ARMv8.1" .github/workflows/xnu.yml
91:      - name: Build
188:      - name: Verify PRA preemption diagnostics are linked
344:      - name: Check for ARMv8.1 LSE instructions (Cortex-A53 has none)
$ grep -n "0198" .github/workflows/xnu.yml
324:          # 0198 non-digitizer power-key control guard: the delayed consumer
$ grep -n "0196 never entered\|Skipping patch" .github/workflows/xnu.yml | cut -c1-58
147:            || { echo "0196 never entered the apply phase";
150:          ! grep -E "Skipping patch .*(0176-pra-emmc|0
```
(both lines `cut` at 58 columns: :150's regex continues through
`0196-pra-touch)` on the same line — no patch later than 0196 is named in it.)
DIRECT PROOF that the format strings are in a built kernel (not an inference
from a green step list), taken from the FLASHED T21a image: its payload is the
CI kernel 82012c03, decompressed with `tools/pra_package.sh:79-84`'s own recipe
(gzip at image offset 0x800):
```
$ python3 -c 'import gzip;d=open("out/pra-0198-t21.img","rb").read();open("/tmp/t21a_payload.bin","wb").write(gzip.decompress(d[0x800:]))' && strings -a /tmp/t21a_payload.bin | grep -F 'SWEET HID: powerkey'; echo "rc=$?"
SWEET HID: powerkey arm secs=%u err=%u armed=%d clients=%u
SWEET HID: powerkey %u down (interval %u s) usage 0x%x
SWEET HID: powerkey %u up
SWEET HID: powerkey done
rc=0
```
Four format strings, and the arm one is the 0198 form (`secs=%u err=%u`, no
0199 `every=%u`) — so this also proves the T21a kernel carries 0198 only. The
same thing in its literally requested form,
`strings -a out/ci/kernel.development.pra | grep -F 'SWEET HID: powerkey'`,
was also run on the 2026-11-22 20:19 build of `out/ci` (sha256
`4ebc18bb65528a4fd5b50ad0ee13d8711e99f3cd6ba94e4e72b39782bdd99c3f`, 17,224,552 B):
```
$ strings -a out/ci/kernel.development.pra | grep -F 'SWEET HID: powerkey'; echo "rc=$?"
SWEET HID: powerkey arm secs=%u every=%u err=%u armed=%d clients=%u
SWEET HID: powerkey %u down (interval %u s) usage 0x%x
SWEET HID: powerkey %u up
SWEET HID: powerkey done
rc=0
```
that build is post-0199 (the `every=%u` field). That `out/ci` was rebuilt and
emptied by a concurrent session at 20:27, so the file is no longer on disk —
re-run this against a fresh artifact; the image proof above is the durable one.
Caveat, VERIFIED by the second grep: "0198" appears in the workflow ONLY at that
comment — the apply-phase greps (xnu.yml:107-147) stop at 0196 and the skip regex
(:150) names patches through 0196, so a silently skipped 0198 would not trip the
skip detector; it trips this marker assert instead (string absent). Note the 0198
marker is a SUBSTRING of 0199's (`SWEET HID: powerkey` is contained in
`SWEET HID: powerkey arm secs=`), so the 0198 assert stays green for every later
build; 0200 adds no string and its only guard is the 0199 assert plus the
apply-phase grep (xnu.yml:330-333).

## 4. Arithmetic (python3, quoted)

```
$ python3 -c 'print(2*(60+4), 16384//(2*(60+4)), 2*(60+4)/16384, 64*4)'
128 128 0.0078125 256
$ python3 -c 'print(0.1, 120+0.1, 120+0.2, 100)'
0.1 120.1 120.2 100
```
A pair is 128 B = 0.78 % of the 16,384 B queue and 128 pairs would fill it; the
release follows its press by 100 ms, the second press starts 120.1 s after the
first and the timer stops 120.2 s in.

## 5. Base-file anchors (the path the control reuses)

`key()` 428-438 (event :430, `SWEET HID: key 0x%x %s (%u clients)` :433-434,
`dispatchEvent` :435), `dispatchEvent` 206-229 with the 1 s-gated `event size=`
printf (:216-221) and the client loop (:223-228) that discards the event when
the array is empty, `handleOpen` appending to `_clients` (:141-164):
```
$ sed -n '668,675p' work/0198/SweetHID-pre0198.cpp
/* key: 0 power (side button), 1 volume up, 2 volume down, 3 home */
extern "C" void
sweet_hid_key(int key, int down)
{
	static const UInt32 usages[] = {
		kHIDUsage_Csmr_Power, kHIDUsage_Csmr_VolumeIncrement,
		kHIDUsage_Csmr_VolumeDecrement, kHIDUsage_Csmr_Menu,
	};
```
Those names resolve to 0x30 / 0xE9 / 0xEA / 0x40
(`IOHIDUsageTables.h:991 kHIDUsage_Csmr_Power = 0x30, /* On/Off Control */`;
`:1114 kHIDUsage_Csmr_VolumeIncrement = 0xE9`; `:1115 ...VolumeDecrement =
0xEA`; `:999 kHIDUsage_Csmr_Menu = 0x40`; page Consumer, `:980
kHIDUsage_Csmr_ConsumerControl = 0x01`). 0198 presses index 0 then index 1's
usage (post:507-508, 515-516), so a positive is comparable with the standby
`sweethidtest` path that already drives `key()` (pre:450).

## 6. Supporting anchors for the claim's K2, K4, K7

```
$ grep -c "sweet_hid_key" xnu-src/bsd/dev/a5xelte_keys.c xnu-src/bsd/dev/sweet_keys.c; grep -n "A5_KEYS_DEFAULT" xnu-src/pexpert/pexpert/arm64/PRA.h; grep -n "a5xelte_keys_init();" xnu-src/iokit/bsddev/IOKitBSDInit.cpp
xnu-src/bsd/dev/a5xelte_keys.c:2
xnu-src/bsd/dev/sweet_keys.c:2
63:#define A5_KEYS_DEFAULT               0
805:	a5xelte_keys_init();
$ grep -c "buttons registered" work/ring61-true.txt work/ring62-full.txt; grep -n "SweetHIDButtons open\|queue mapped by SweetHIDButtons" work/ring62-full.txt; grep -c "a5fb_keep_on=1" tools/pra_package.sh work/ring62-full.txt
work/ring61-true.txt:0
work/ring62-full.txt:0
996:SWEET HID: SweetHIDButtons open by IOHIDEventServiceUserClient -> 1
997:SWEET HID: queue mapped by SweetHIDButtons
tools/pra_package.sh:2
work/ring62-full.txt:1
```
`a5xelte_keys.c` is the Exynos7580 ALIVE GPIO poll, `#if
defined(ARM64_BOARD_CONFIG_A5XELTE)` at :8 and compiled on PRA: its init runs at
IOKitBSDInit.cpp:805, takes `A5_KEYS_DEFAULT` (:107) from PRA.h:63 = 0 and
returns at :113-115 printing `A5XELTE KEYS: disabled` before mapping ALIVE, so
no pin is polled and `sweet_hid_key()` (:94) is never reached here.
`sweet_keys.c` is the PM6150L variant under `ARM64_BOARD_CONFIG_SWEET` (:7)
with no call site on this board. That early print is lost
(`grep -c "A5XELTE KEYS" work/ring62-full.txt` → `0`), the same class of loss that
swallowed 0198/0199's arm report (§7). The service client is open and the queue
mapped early (ring62:996-997), so `clients=1` is the expected steady state and
`(0 clients)` on a key line means that press beat backboardd's map.

K7, CORRECTED — the `a5fb_keep_on=1` default (tools/pra_package.sh, and T20's
cmdline, one hit in ring62) does route a sleep request to
`SweetFramebuffer.cpp:628-630`, i.e. to `A5XELTE FB: display-off request ignored
(keep_on)` instead of `SWEET FB: display off` — but that line is BASELINE NOISE,
not a positive. It fires on boots with NO key event anywhere in them:
```
$ for f in ring34 ring52-fresh ring53-fresh ring54-fresh ring55-full ring56-full ring57-full ring58-full ring59-full ring61-true ring62-full ring63-full; do printf "%-14s %s\n" "$f" "$(grep -c 'display-off request ignored' work/$f.txt)"; done
ring34         2
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
(`work/ring61-full.txt` reads 0 only because it is the 515-line short pull, not
because that boot was clean.) `work/ring34-notes.md:22` already named it:
`"A5XELTE FB: display-off request ignored (keep_on)" x2 — the idle display-off IS
ignored for the panel`, on the wedge boot that carried no key event at all. In
ring63 the two hits are :1782 and :2634 — after the power pair and ~1000 lines
after `powerkey done` (:1629) — so neither is adjacent to a press. Under the
default `a5fb_keep_on=1` the ring therefore carries NO event-attributable display
signal; the positive is the user's visual report, or a baseline-count INCREASE
(3 where this boot showed 1-2) landing temporally adjacent to a press.

## 7. ring63: the arm line never landed, and which queue is which

(1) THE ARM REPORT IS ABSENT from the text dump AND from the raw image, so it was
never emitted (not truncated):
```
$ grep -c "arm secs" work/ring63-full.txt; echo "grep rc=$?"; strings -a work/ring63.raw | grep -c "arm secs"; echo "strings|grep rc=$?"
0
grep rc=1
0
strings|grep rc=1
```
0198/0199 armed that report 30 s after `SweetHIDButtons::start()` and `start()`
sits ~5 s into the boot (INFERRED — 0200's estimate; nothing in the ring dates
it), so it fired at ~+35 s, before IOLog reaches the ring (`buttons registered`
→ 0 hits in ring61/ring62/ring63). What the failure leaves open is `fKeyErr`
2/3/4: unobservable, so a boot with no key lines stays as ambiguous as T20's.
0200 (`xnu/patches/0200-pra-power-key-arm-report.patch`, commit aa18a99) re-times
the report to `prapowerkey` seconds and redefines `armed=` as "allocated AND
`err == 0`"; the arm line is expected in ring64, not ring63.

(2) TWO SERVICES, TWO QUEUES. The `queue stats` line carries no service name, so
attribution rests on the two `queue mapped by` lines plus the senderID stamped by
`dispatchEvent` (`event->setSenderID(getRegistryEntryID())`, post:210):
```
$ grep -n "queue mapped by\|SweetHIDButtons open\|sender=" work/ring63-full.txt
1017:SWEET HID: queue mapped by SweetHIDTouch
1020:SWEET HID: event size=236 sender=0x100000128
1030:SWEET HID: SweetHIDButtons open by IOHIDEventServiceUserClient -> 1
1031:SWEET HID: queue mapped by SweetHIDButtons
1123:SWEET HID: event size=60 sender=0x100000127
1625:SWEET HID: event size=60 sender=0x100000127
2537:SWEET HID: event size=236 sender=0x100000128
2547:SWEET HID: event size=236 sender=0x100000128
2551:SWEET HID: event size=236 sender=0x100000128
```
`0x100000127` rides every 60 B key event and `0x100000128` every 236 B digitizer
event. Each service's user client owns its OWN queue and its OWN counters
(`kQueueSizeMax` 16384, IOHIDEventServiceUserClient.cpp:38, :265; `_queue`/
`_eventCount`/`_droppedEventCount` are that class's members, .h:59-67), so a key
press is counted in SweetHIDButtons' 16 KiB queue — never in the digitizer's:

```
$ grep -n "queue stats" work/ring63-full.txt
1021:SWEET HID: queue stats enq=0 drop=0 type=0 head=0 tail=0
1124:SWEET HID: queue stats enq=0 drop=0 type=0 head=0 tail=0
1626:SWEET HID: queue stats enq=2 drop=0 type=3 head=128 tail=128
2538:SWEET HID: queue stats enq=2 drop=0 type=11 head=480 tail=480
2548:SWEET HID: queue stats enq=26 drop=0 type=11 head=6240 tail=6240
2552:SWEET HID: queue stats enq=94 drop=0 type=11 head=6240 tail=6240
2864:SWEET HID: queue stats enq=110 drop=0 type=11 head=10080 tail=10080
2879:SWEET HID: queue stats enq=113 drop=0 type=11 head=10800 tail=10800
3195:SWEET HID: queue stats enq=115 drop=0 type=11 head=11280 tail=11280
3200:SWEET HID: queue stats enq=166 drop=0 type=11 head=7200 tail=7200
3213:SWEET HID: queue stats enq=231 drop=0 type=11 head=6480 tail=6480
3219:SWEET HID: queue stats enq=272 drop=0 type=11 head=16320 tail=16320
3222:SWEET HID: queue stats enq=280 drop=0 type=11 head=1920 tail=1920
```
The two button-queue lines are :1124 (all zeros: the first print for THAT queue,
taken before the down event is counted) and :1626 (`enq=2` = the pair, `type=3` =
keyboard, IOHIDEventTypes.h:94, `head=tail` = drained). The key-pair charge is
`2*(60+4)` per pair = 128 B, i.e. 64 B per event, which is exactly `head=128`:
```
$ python3 -c 'print(2*(60+4), 128//64, 64*2)'
128 2 128
```
Everything from :2538 on (`type=11`, `head` in 240 B strides) is the TOUCH queue
and says nothing about the key pair — the earlier `enq=2 ... type=11 head=480`
reading was the digitizer service's queue, which is also why "subtract the
selftest's +2" was wrong: that +2 lands in a different queue's counters.

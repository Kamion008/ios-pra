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
`git apply --check` is recorded but is NOT proof — AGENTS.md:44-49: local git
2.56 skip-detects an already-applied patch at rc=0. The GNU dry run, the real
apply and the byte compare are the three real legs; both `cmp`s compare against
the same durable post file, which is what makes the legs byte-level.

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
`strings -a` finds it in any kernel built with the patch; CI run 45055479729 on
89d95c6 (`work/ci-0198.log`) shows the Build step completed without a failure
tail, i.e. the assert ran and passed. Caveat, VERIFIED by the second grep:
"0198" appears in the workflow ONLY at that comment — the apply-phase greps
(xnu.yml:107-147) stop at 0196 and the skip regex (:150) names patches through
0196, so a silently skipped 0198 would not trip the skip detector; it trips this
marker assert instead (string absent).

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
(`grep -c "A5XELTE KEYS" work/ring62-full.txt` → `0`), the same class of loss as
`start()`'s own lines — which is why 0198 reports its arm from a 30 s timer
(post:457-460, 485-492). The service client is open and the queue mapped early
(ring62:996-997), so `clients=1` is the expected steady state and `(0 clients)`
on a key line means that press beat backboardd's map. The `a5fb_keep_on=1`
default (tools/pra_package.sh, and T20's cmdline — one hit in ring62) sends the
sleep request to `SweetFramebuffer.cpp:628-630`, i.e. `A5XELTE FB: display-off
request ignored (keep_on)` instead of `SWEET FB: display off`.

# EVIDENCE - 0196: the synthetic bottom-edge unlock swipe

Patch: `xnu/patches/0196-pra-touch-swipe.patch` (142 lines, SweetHID.cpp
only). Generated against the exact post-0195 file: `work/ci193/pre0193` +
0193 + 0194 + 0195 applied with `git apply --include=.../SweetHID.cpp`.
Durable before/after: `work/0196/SweetHID-pre0196.cpp` and
`work/0196/SweetHID-post0196.cpp`.

## 1. Three-way verify (captured output)

```
$ git apply --check -p1 0196-pra-touch-swipe.patch; echo "rc=$?"
rc=0
$ patch -p1 --fuzz=0 --dry-run < 0196-pra-touch-swipe.patch; echo "rc=$?"
checking file iokit/Kernel/arm/hid/SweetHID.cpp
rc=0
$ git apply -p1 0196-pra-touch-swipe.patch; echo "rc=$?"
rc=0
$ cmp iokit/Kernel/arm/hid/SweetHID.cpp work/0196/SweetHID-post0196.cpp; echo "rc=$?"
rc=0
```
`git apply --check` is recorded but not proof (skip-detects applied
patches at rc=0); the GNU dry run and the byte compare are the real legs.
Hunk accounting (awk over the file): 4 hunks, adds 15+5+19+45 =
84, deletes 0; old starts 363/379/485/581, new starts 363/394/505/620,
each `ctx+del==oldc` and `ctx+add==newc` True. Literal counts:
`pratouchswipe` 3, `swipeFired` 3, `SWEET HID: swipe` 5,
`fSwipe = NULL` 1, `interval %u s` 1, `180 ms` 1.

## 2. Arithmetic (python3, quoted)

```
$ python3 -c 'print(1920 - 1 - 48, 1914 > 1920 - 1 - 48, 1919 - 1914)'
1871 True 5
$ python3 -c 'print([1914 - 150*k for k in range(9)], 1914-714)'
[1914, 1764, 1614, 1464, 1314, 1164, 1014, 864, 714] 1200
$ python3 -c 'print((1+8)*20, [420 + 120*k for k in range(3)], 1080//2)'
180 [420, 540, 660] 540
```
The down is 5 px above the last panel row (1914 vs 1919) and 6 px above
the 1920-px panel bottom; either way it is inside the 48 px band. It
normalizes into the presented 1125x2436 display at x 562.5, down y
2428.4 and release y 905.9:
```
$ python3 -c 'print(540*1125/1080, 1914*2436/1920, 714*2436/1920)'
562.5 2428.3875 905.925
``` Real
starts: 420 s, 540.18 s, 660.36 s (each run ends with a 180 ms gesture
before the 120 s re-arm).

## 3. The touch() body the swipe reuses (post-0195 file, line numbers of
`work/0196/SweetHID-pre0196.cpp`, which is the pre-patch file)

```
516		if (!was && down) {
518			fEdge[finger] = x < SWEET_TOUCH_EDGE_PX || x > fPanelW - 1 - SWEET_TOUCH_EDGE_PX ||
519			    y < SWEET_TOUCH_EDGE_PX || y > fPanelH - 1 - SWEET_TOUCH_EDGE_PX;
542		UInt32 mask = fEdge[i] ? kIOHIDDigitizerEventFromEdgeTip : 0;
557		child->setIntegerValue(kIOHIDEventFieldDigitizerEventMask, mask);
560		cmask |= mask;
```
The edge bit is applied to every finger child and accumulated onto the
collection. The latch is set only on the `!was && down` transition
(516-521), so the eight moves and the release reuse the down value and
the whole contact carries the flag.

fPanelH = 1920: xnu/patches/0194-pra-touch-panel-init.patch:48-49 sets
`fPanelW = 1080; fPanelH = 1920;` in the compiled arm, and T19's runtime
clamp line (`selftest 2000,3000 -> 1079,1919`) proves the values live.
NB: `SWEET HID: panel arm` / `surface` / `touch registered` have 0
occurrences in ring61 - those start() IOLog lines ran before the pralog
ring existed. 0196 therefore prints no "armed" line; the first swipe line
carries the interval.

## 4. Timer lifecycle (in-tree precedent, same file)

```
395		if (PE_parse_boot_argn("sweethidtest", &fTestSecs, sizeof(fTestSecs)) && fTestSecs) {
396			fTest = IOTimerEventSource::timerEventSource(this, &SweetHIDButtons::testFired);
397			if (fTest && _hidWorkLoop->addEventSource(fTest) == kIOReturnSuccess) {
398				fTest->setTimeoutMS(fTestSecs * 1000);
432			sender->setTimeoutMS(press ? 100 : self->fTestSecs * 1000);
445		PE_parse_boot_argn("sweetfb_native", &native, sizeof(native));
446		if (PE_parse_boot_argn("pratouchselftest", &selftest,
```
testFired presses Menu/Home only (430-431 `self->key(kHIDUsage_Csmr_Menu,
press);`). The button timer arms in start() and re-arms from inside its
own action (432), which is exactly 0196's pattern; `IOTimerEventSource.h` is
included and `_hidWorkLoop` is the same member that class uses. Neither
timer is cancelled - the service lives for the kernel's life.

## 5. Donor comparison (captured)

```
$ test -f ../ios-a5xelte/xnu/patches/0058-sweet-hid-event-services.patch && \
  test -f xnu/patches/0058-sweet-hid-event-services.patch && \
  cmp ../ios-a5xelte/xnu/patches/0058-sweet-hid-event-services.patch \
      xnu/patches/0058-sweet-hid-event-services.patch; echo "cmp rc=$?"
cmp rc=0
```

## 6. Prior-art check (quoted)

```
$ grep -c "SMP --- sample" work/ring61-true.txt
7
$ grep -c "SMP Setup\[" work/ring61-true.txt
0
$ grep -c "IOK " work/ring61-true.txt
0
$ grep -c "SWEET KEYS" work/ring61-true.txt
0
```
0161 (quoted): "never attaches on this eMMC phone, so sweetsample has been
dead here since 0054 (0 \"SMP\" lines in ring17 despite the default
boot-arg)." `sweet_keys_init`'s only call site is 0060's sweet_ufs hook.
HANDOFF_2026-11-20's four candidates (HIDEventSystem loop, senderID,
SpringBoard router, payload parser) never landed.

## 7. Ring61 baseline for the positive signal

```
$ grep -n "SWEET FB: swap" work/ring61-true.txt | cut -c1-45
1656:SWEET FB: swap 1 layer 0 surface 2
1677:SWEET FB: swap 2 layer 0 surface 3
1694:SWEET FB: swap 3 layer 0 surface 2
2535:SWEET FB: swap 6 layer 0 surface 3
2799:SWEET FB: swap 7 layer 0 surface 2
2800:SWEET FB: swap 9 layer 0 surface 2
2807:SWEET FB: swap 11 layer 0 surface 2
2917:SWEET FB: swap 12 layer 0 surface 3
2924:SWEET FB: swap 13 layer 0 surface 2
$ wc -l work/ring61-true.txt
3703 work/ring61-true.txt
$ grep -cE "^SWEET AKS:.*sel (9|12)( |$)" work/ring61-true.txt
0
$ grep -cE "^SWEET AKS:" work/ring61-true.txt
966
$ grep -cE "^SWEET AKS: SpringBoard" work/ring61-true.txt
124
$ grep -m1 "SWEET AKS: SpringBoard" work/ring61-true.txt | cut -c1-60
SWEET AKS: SpringBoard sel 0 arg0 0 in 0/0 out 0/0 ->
```
The AKS line format is `SWEET AKS: <proc> sel <N> ...`, so the sel 9/12
zero is measured, not a regex artifact. The swap log is capped: 0046 has
`if (sweet_fb_swaps_logged < 16)` around the print and skips draws with a
null surface, which is why the printed counter skips (1,2,3,6,7,9,11,12,13);
the printed counter reached 13 of the 16 entries, so at most 3 more
lines can appear and absence proves nothing. The T4 decode names sel 9/12 as the real unlock class
(work/boots.md:44). The keybag is a no-passcode stub
(tools/mkiosroot.sh:225-230), so a successful unlock cannot show a keypad.

Frame census from the past rings (python3 over work/ring*.txt; the 0046 swap
log is capped at 16 lines and skips masked/null-surface draws, so the
printed counter is a lower bound on presents):
```
ring  logged  max_counter  last_swap_line / total_lines
28       6        7         1710 / 20122
29       2        3          938 / 17514
30       3        3         1027 / 16999
31       4        4         1005 / 16898
32       5        5         1621 / 17167
33       5        5         1571 / 17117
34      10       15         2046 / 15908
52       6       12         2666 /  5752
53       6        8         2556 /  5741
54      11       17         2827 /  3041
55       8       12         2795 / 12002
56       9       16         2847 / 12025
57       9       18         2506 / 12014
58       9       15         2814 / 12006
59       4        4         1566 /  2349
61       9       13         3169 /  3948
```
Every boot presented at least 3-18 frames (counter jumps prove unlogged
presents), but in all 16 rings the last logged present is early and
hundreds to thousands of lines of activity follow it (ring34: 13,862 lines
after; ring61: 779). No present line appears late in any ring. INFERRED:
the lock screen settles on one image and stops presenting; the log cannot
count total frames, but it never records a late one - consistent with the
user's "never seen more than one frame" memory. This is why T20's
decisive signals are the screen on return and AKS sel 9/12, not swaps.

## 8. Reviewer rounds (opencode/deepseek-v4.1-flash-free, plan agent)

- Round 1 (`work/pkt-171401/report.md`): 2 refuted / 7 weak / 2 survive.
  Real refuted finding: `fSwipeStep`/`fSwipeRuns`/`fSwipe` were not
  initialized. Fixed (all four set before arming). Also corrected the
  duration arithmetic to 180 ms.
- Round 2 (`work/pkt-171816/report.md`): 1 refuted / 6 weak. Real refuted
  finding: the start() "armed" line would never appear because start()
  precedes the pralog ring. Fixed: no "armed" line; the first swipe line
  carries the interval. Also added the child-mask quote, the swap line
  numbers, the sel 9/12 source and the durable cmp path.
- Round 3 (`work/pkt-172231/report.md`, saved as work/0196-review.txt):
  1 refuted / 7 weak. Real refuted finding: `+87` was wrong (hunk adds are
  86). Fixed. Also fixed: pre-file (not post-file) mask line numbers,
  re-arm-from-action precedent (432), `PE_parse_boot_argn` precedent,
  all eight moves logged with a distinct `release` line, swap-log cap and
  AKS format/census, "5 px above the last row".
- Round 4: run on this text and the final patch; verdict in
  `work/0196-review.txt` (appended).

## 9. What T20 must show

- `SWEET HID: swipe 1 start (interval 420 s) at 540,1914`, `move 1/8`
  through `move 8/8` at y=1764..714, then `swipe 1 release at 540,714`;
  runs 2 and 3 follow at ~540 s and ~660 s.
- A burst of new `SWEET FB: swap` lines (at most 3 remain under the cap;
  ring61 printed 9 of 16, the counter reached 13) and/or SpringBoard AKS
  sel 9/12 after a swipe = the UI processed the gesture (baseline: 0
  sel 9/12).
- USER NOTE (2026-11-22): the lock screen has never been seen to draw more
  than one frame. A static lock screen adds no swap lines, so an absence of
  swaps after the swipe is expected and is NOT a failure signal; the
  decisive read is the visible screen on return (home screen vs lock
  screen) plus AKS sel 9/12, with swap lines only a bonus.
- No AKS and an unchanged lock screen = the gesture was not visibly
  accepted; the follow-up probes must separate gesture-rejected,
  backboardd-dispatch and SpringBoard-routing.

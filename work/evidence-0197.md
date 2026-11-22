# EVIDENCE — 0197: the T20 outcome (ring62 decode)

Every block below is a captured command and its output from the
2026-11-22 session. Line numbers are LF-based lines of
`work/ring62-full.txt`. No number in claim-0197.md is written from mental
arithmetic; each derived figure appears here with the tool that produced it.

## 1. Ring identity and freshness

```
$ PRA_SERIAL=$PRA_SERIAL OUT=work/ring62.raw TXT=work/ring62-full.txt sh tools/pra_readlog.sh
dump: work/ring62.raw (4194914 bytes, LBA 794623 + 8193)
version 1 ring 4 MiB total 202057 seq 11
---- full ring written to work/ring62-full.txt (202057 bytes) ----
  yes host mapped      2      yes launchd        126
  yes root device      1      yes backboardd      35
  yes SpringBoard     56      no  panic            0
```

No `NOTE: header total ... is stale` line was printed this time, so the
readlog NUL-end path was not needed: the header total (202057) equals the
first NUL. That is the opposite of ring61 (header 35665 vs NUL 216150).

```
$ cmp work/ring61.raw work/ring62.raw
work/ring61.raw work/ring62.raw differ: byte 17, line 1
rc=1
$ sha256sum work/ring62-full.txt
6f184b482092ea4dd2548a6c297b3760580cda696a43369f944f6a5c9cb34b35  work/ring62-full.txt
```

Byte 17 is the second byte of the little-endian `total` field, so the
difference is the boot's own byte count: a real new boot, not stale
content.

## 2. The gesture (K1) — `grep -n "SWEET HID: swipe" work/ring62-full.txt`

```
1598:SWEET HID: swipe 1 start (interval 420 s) at 540,1914
1604-1616: SWEET HID: swipe 1 move 1/8..8/8 at 540,{1764,1614,1464,1314,1164,1014,864,714}
1618:SWEET HID: swipe 1 release at 540,714
2047:SWEET HID: swipe 2 start (interval 420 s) at 540,1914
2053-2060: swipe 2 move 1/8..8/8, same y ladder
2062:SWEET HID: swipe 2 release at 540,714
2481:SWEET HID: swipe 3 start (interval 420 s) at 540,1914
2486-2493: swipe 3 move 1/8..8/8, same y ladder
2495:SWEET HID: swipe 3 release at 540,714
2496:SWEET HID: swipe selftest done
```

```
$ grep -c "SWEET HID: swipe" work/ring62-full.txt
31
$ grep -n "SWEET HID: selftest raw 2000,3000" work/ring62-full.txt
980:SWEET HID: selftest raw 2000,3000
$ sed -n '980,983p' work/ring62-full.txt
SWEET HID: touch 0 down at 1079,1919 edge
SWEET HID: event size=236 sender=0x100000131
SWEET HID: queue stats enq=0 drop=0 type=0 head=0 tail=0
SWEET HID: touch 0 up at 1079,1919 edge
```

The control therefore fired before the first swipe — the 2000,3000 raw
point was clamped to 1079,1919 again (0194 effective on an independent
boot).

## 3. Event accounting (K2, K3, K7)

```
$ grep -n "queue stats" work/ring62-full.txt
982:SWEET HID: queue stats enq=0 drop=0 type=0 head=0 tail=0
1601:SWEET HID: queue stats enq=2 drop=0 type=11 head=480 tail=480
2050:SWEET HID: queue stats enq=12 drop=0 type=11 head=2880 tail=2880
2484:SWEET HID: queue stats enq=22 drop=0 type=11 head=5280 tail=5280
$ grep -n "SWEET HID: event size=" work/ring62-full.txt
981, 1600, 2049, 2483 — all `event size=236 sender=0x100000131`
$ grep -n "SWEET HID: touch" work/ring62-full.txt
980 (selftest down) 983 (selftest up) 1599/1617 2048/2061 2482/2494
```

enq series 0, 2, 12, 22: deltas 2 (selftest down+up), 10, 10 = one event
per touch() call (down + 8 moves + up = 10). head == tail at every sample.
The last sample sits at run 3's `down`, so run 3's own 10 events were never
sampled: INFERRED total 32 = 3 x 10 + 2.

```
$ python3 -c "print('240*22 =', 240*22); print('236*22 =', 236*22)"
240*22 = 5280
236*22 = 5192
$ python3 -c "print(hex(0x100000126), 0x100000126, hex(0x100000131), 0x100000131, 0x100000131-0x100000126)"
0x100000126 4294967590 0x100000131 4294967601 11
```

`head` advances 240 B per event while the printed serialization is 236 B
(python3: 240*22 = 5280 vs 236*22 = 5192, a 4 B per-event difference).
UNKNOWN: which figure is the payload vs the queue slot. The delivery
conclusion does not depend on it — head==tail and drop=0 do.

```
$ grep -o "event size=[0-9]* sender=0x[0-9a-f]*" work/ring61-true.txt | sort | uniq -c
     17 event size=236 sender=0x100000131
```

Ring61 (T19) logged the same senderID on 17 lines, so K7's "not a signal"
is direct: the difference from T16's 0x100000126 is per-boot ordering.

## 4. Acceptance (K4) — AKS comparison

```
$ grep -cE "^SWEET AKS:.*sel (9|12)( |$)" work/ring62-full.txt
0
$ for f in work/ring62-full.txt work/ring61-true.txt; do echo "$f:"; \
    grep -oE "SWEET AKS:.*sel [0-9]+" "$f" | grep -oE "sel [0-9]+" | sort -k2 -n | uniq -c | sort -rn; done
work/ring62-full.txt:            work/ring61-true.txt:
    511 sel 17                    619 sel 17
     98 sel 7                      99 sel 7
     95 sel 0                      95 sel 0
     65 sel 10                     63 sel 10
     55 sel 35                     58 sel 35
      6 sel 27                     11 sel 27
      6 sel 26                     11 sel 26
      4 sel 8                       3 sel 14
      3 sel 14                      2 sel 32
      2 sel 32                      2 sel 31
      2 sel 31                      1 sel 8
      1 sel 103                     1 sel 103
      1 sel 102                     1 sel 102
```

Neither ring contains a `sel 9` or a `sel 12` line at all — the baseline
is absence, not a counter at zero, and T20 did not change it. `sel 8`
still returns 0xe00002c7 (Unsupported):

```
$ grep -n "SWEET AKS: SpringBoard sel 8" work/ring62-full.txt
2102, 2439, 2444, 2806 — all `sel 8 arg0 0 in 1/0 out 0/0 -> 0xe00002c7`
```

Screen state on return (user report, not a measurement): the lock screen
was unchanged, apparently with no new frames drawn ("it looks like").
Recorded as INFERRED — the ring cannot show it.

## 5. The confound (K5) — the cmdline the kernel received

```
$ python3 -c "..."   # tail of the launchd 'boot-args =' line
work/ring62-full.txt:233  tail 475 B
  ... sweetsample=Setup praexecskip=... pratouchswipe=420 pratouchselftest=1 pratouchdbg=1
  pratouch=1: 0   pratouchswipe: 1   pratouchreset: 0   pratouchdbg: 1
work/ring61-true.txt:260  tail 484 B
  ... pratouch=1 pratouchreset=1 pratouchdbg=1 pratouchselftest=1
  pratouch=1: 1   pratouchswipe: 0   pratouchreset: 1   pratouchdbg: 1
```

Independent cross-check straight from the packaged image:

```
$ python3 -c "gzip payload at 0x800 of out/pra-xnu.img; find b'debug=0xc'"
cmdline 475 B:
debug=0xc serial=3 cpus=4 keepsyms=1 rd=sdhcroot0 emmcroot=userdata emmcprobe=1
emmcwrite=1 rootrw=1 unentitled_ios_sim_launch=1 launchd_unsecure_cache=1
ignition_level=1 wdt_test=no_user_checkin wdt=-1 emmcstats=1 pralog=1
praloglba=794623 sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1
sweetfb_hz=1 sweetsample=Setup praexecskip=locationd,WirelessRadioManagerd,
fairplayd.H2,bluetoothd,nanotimekitcompaniond,CommCenter pratouchswipe=420
pratouchselftest=1 pratouchdbg=1
  pratouch=1            0
  pratouchreset=1       0
  pratouchswipe=420     1
  pratouchselftest=1    1
  pratouchdbg=1         1
  pralog=1              1
  praloglba=794623      1
total args: 26
```

The ring's silence matches: with `pratouch=1` absent the 0172 probe never
ran, so there is no touch-driver telemetry at all:

```
$ for p in "PRA touch" "app mode confirmed" "reports=" "hid inject"; do ... done
                          ring62   ring61-true
PRA touch                     0          104
app mode confirmed            0            1
reports=                      0           84
hid inject                    0            1
```

Note (do not misread this): the local `xnu-src/` tree contains
`SweetHID.cpp` but no `PRA touch` string, because the pra_touch driver
lives only in the patch stack (0172, 0177-0189). A grep of that tree says
nothing about what the T20 kernel contained.

## 6. SpringBoard was alive (K8)
```
$ grep -n "SWEET SURF: SpringBoard\|SWEET FB: swap\|SWEET FB: display on" work/ring62-full.txt | awk -F: '$1<1600'
1110:SWEET FB: display on
1125:SWEET SURF: backboardd create id 2 1080x1920 ...
1135:SWEET FB: swap 1 layer 0 surface 2 1080x1920 ...
1143:SWEET FB: swap 2 ...
1191:SWEET FB: swap 3 ...
1508:SWEET SURF: SpringBoard sel 40
$ grep -n "SWEET SURF: SpringBoard create" work/ring62-full.txt
2291 id 4 272x184 | 2293 id 5 312x202 | 2294 id 6 230x186
2431 id 7 105x144 | 2432 id 8 102x144 | 2433 id 9 360x246
$ python3 -c "print('1598-1135 =', 1598-1135); print('2496-2436 =', 2496-2436)"
1598-1135 = 463
2496-2436 = 60
$ grep -n "exec SpringBoard\|exec backboardd" work/ring62-full.txt
478:exec SpringBoard
544:exec backboardd
```

The lock screen was presented 463 lines before swipe 1, and SpringBoard
created five more surfaces after it — so "SpringBoard had no UI yet" and
"SpringBoard is wedged" both fail against the ring.

The second `display on` is not a swipe reaction either — the same triple
appears in the touch-free ring61:

```
$ grep -n "SWEET FB: display" work/ring62-full.txt
1110:SWEET FB: display on
2171:SWEET FB: display on
$ sed -n '2171,2173p' work/ring62-full.txt
SWEET FB: display on
SWEET FB: backboardd sel 79 in 2/0 out 0/40 -> 0x0
SWEET FB: swap 6 layer 0 surface 3 1080x1920 ...
$ grep -n "SWEET FB: display" work/ring61-true.txt
1625:SWEET FB: display on
2533:SWEET FB: display on
$ sed -n '2533,2535p' work/ring61-true.txt
SWEET FB: display on
SWEET FB: backboardd sel 79 in 2/0 out 0/40 -> 0x0
SWEET FB: swap 6 layer 0 surface 3 1080x1920 ...
```

ring61 had no swipe at all (0 `SWEET HID: swipe` lines) and still logs the
identical `display on` / `sel 79 (0/40)` / `swap 6` triple, so that burst is
a recurring boot pattern, not a gesture reaction.

## 7. Frame-log limits (do not turn these into a frame count)

```
$ grep -n "swaps_logged" xnu/patches/0046-sweet-iosurface-iomfb.patch
1213:+static uint32_t sweet_fb_swaps_logged;
1243:+		if (sweet_fb_swaps_logged < 16) {
1244:+			sweet_fb_swaps_logged++;
$ grep -n "SWEET FB: swap" work/ring62-full.txt   # counters
1135:1  1143:2  1191:3  2173:6  2336:7  2337:8  2340:14  2436:15
```

8 lines printed, counters reaching 15 of the 16-entry cap: at most ONE
more swap line could ever have appeared this boot, and the counters are
non-contiguous (4, 5, 9-13 never printed) because masked/null-surface
draws are skipped. The last swap (2436) is 60 lines before the last swipe
line (2496). Absence of swaps after a swipe remains NOT a failure signal.

## 8. Health

```
panic                        0
PRA LOG: strat flush       890   (last: total=201453 err=0 skipped=0)
PRA LOG: write failed        9   (last at 2536, "after 64 ticks (lock=64 card=0)")
exec lines                1077   (841 xpcproxy, 9 com.apple.datamigrator, rest <= 2)
last ring line            3606  "exec xpcproxy"
```

## 9. Reviewer and second-opinion record

- Premium second opinion (Claude Sonnet 5.5) on the three branches:
  ranked (iii) routed-but-never-accepted ~65%, (ii) dispatch drop ~25%,
  (i) gesture rejected ~10%; proposed a non-digitizer control (synthetic
  power key) and aiming the sampler at SpringBoard/backboardd. Two side
  claims were checked and rejected: "swipes 1 and 2 had no UI yet" (see
  section 6) and the senderID concern (see section 3).
- ring62 tabulation (DeepSeek V4.1 Flash, high): work/ring62-decode.md.
  Its boot-args line citation (187) was corrected to 233/260, and its
  inference "the kernel had no pra_touch driver", drawn from the
  un-patched local tree, was removed — see section 5's note.
- Docs cross-check (DeepSeek V4.1 Flash, high) raised four points; three
  changed this record and one did not: (a) the first `queue stats` sample
  is 0/0 and so proves nothing about drain — the qualifier was added to
  claim-0197 K3 and to the boots.md row; (b) a second `SWEET FB: display
  on` exists at line 2171 — checked, and ring61 has the same triple
  without any swipe (section 6), so it is a boot pattern, not a reaction;
  (c) "per-boot registration order" was demoted to INFERRED; (d) the arm
  block is at SweetHID-post0196.cpp:515-524 (not 519-525) — no landed file
  cited that number, so no correction was needed.

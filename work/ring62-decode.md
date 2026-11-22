# ring62 decode — factual tabulation

Scope `work/ring62-full.txt` (boot seq 11, XNU 2026-11-22 build + 0196-pra-touch-swipe.patch). Baseline
`work/ring61.raw`/`ring61-full.txt` (seq 1, stale header total) + `ring61-true.txt` (same ring, re-cut at first
NUL). **No adb/fastboot command was run in this session**; every figure comes from the command shown.
Numbering (VERIFIED): `python3 -c "d=open('work/ring62-full.txt','rb').read();print(d.count(b'\n'),d.count(b'\r\n'),d.count(b'\r')-d.count(b'\r\n'))"`
→ `3606 3606 245` (245 bare CR from `\r\r\n`). `grep -n`/`wc -l` split on LF = **3,606 lines**; python
text-mode splits on bare CR = 3,851. **All line numbers below are LF-based.**

## 1. Boot identity
| check | command | output |
|---|---|---|
| header | `python3 -c "import struct;d=open('work/ring62.raw','rb').read();print(d[:7],struct.unpack('<II',d[8:16]),struct.unpack('<QQ',d[16:32]))"` | `b'PRALOG1' (1, 4194304) (202057, 11)` |
| header ring61 | same on `ring61.raw` | `b'PRALOG1' (1, 4194304) (35665, 1)` |
| cmp | `cmp work/ring62.raw work/ring61.raw` | `differ: byte 17, line 1` |
| byte 17 | `python3 -c "print(open('work/ring62.raw','rb').read()[16:32].hex(' '))"` | byte 17 = 2nd byte of LE u64 `total`; `49 15 03 00…`=202057 vs `51 8b 00 00…`=35665 |
| size / lines | `wc -c` / `wc -l work/ring62-full.txt` | `202057` / `3606` |
| text==body | `python3 -c "d=open('work/ring62.raw','rb').read();print(d[512:512+202057]==open('work/ring62-full.txt','rb').read())"` | `True` |
| NUL end | `python3 -c "d=open('work/ring62.raw','rb').read()[512:];print(d.find(b'\x00'),d[202057])"` | first NUL **202057** == `total` (value 0) → no truncation; ring61 first NUL 216150 vs total 35665 → stale/truncated |
| sha256 | `sha256sum work/ring62-full.txt` | `6f184b482092ea4dd2548a6c297b3760580cda696a43369f944f6a5c9cb34b35` |
| file tail | `tail -c 8 work/ring62-full.txt \| xxd` | `exec xpcproxy\r\n` (ends with text, no NUL) |

## 2. Ordered timeline — `grep -n -E "SWEET HID: swipe|SWEET FB: swap|SWEET HID: queue stats|SWEET HID: event size=|SWEET HID: touch" work/ring62-full.txt`
Swap full form: `SWEET FB: swap N layer 0 surface {2|3} 1080x1920 fmt 0x42475241 bpr 4352 a 0,0 1080x1920 b 0,0 1080x1920`.
| line | event | detail |
|---|---|---|
| 980 | touch | `0 down at 1079,1919 edge` (selftest, raw 2000,3000 clamped) |
| 981 | event size | `236 sender=0x100000131` |
| 982 | queue stats | `enq=0 drop=0 type=0 head=0 tail=0` |
| 983 | touch | `0 up at 1079,1919 edge` |
| 1135 / 1143 / 1191 | swap | counters `1` (s2), `2` (s3), `3` (s2) — pre-swipe |
| 1598 | swipe | `1 start (interval 420 s) at 540,1914` |
| 1599 | touch | `0 down at 540,1914 edge` |
| 1600 | event size | `236 sender=0x100000131` |
| 1601 | queue stats | `enq=2 drop=0 type=11 head=480 tail=480` |
| 1604,1605,1606,1607,1613,1614,1615,1616 | swipe | `1 move 1/8…8/8 at 540,1764 / 1614 / 1464 / 1314 / 1164 / 1014 / 864 / 714` |
| 1617 | touch | `0 up at 540,714 edge` |
| 1618 | swipe | `1 release at 540,714` |
| 2047 | swipe | `2 start (interval 420 s) at 540,1914` |
| 2048 | touch | `0 down at 540,1914 edge` |
| 2049 | event size | `236 sender=0x100000131` |
| 2050 | queue stats | `enq=12 drop=0 type=11 head=2880 tail=2880` |
| 2053,2054,2055,2056,2057,2058,2059,2060 | swipe | `2 move 1/8…8/8 at 540,1764 / 1614 / 1464 / 1314 / 1164 / 1014 / 864 / 714` |
| 2061 | touch | `0 up at 540,714 edge` |
| 2062 | swipe | `2 release at 540,714` |
| 2173 | swap | counter `6` (s3) |
| 2336 / 2337 / 2340 / 2436 | swap | counters `7` (s2), `8` (s3), `14` (s3), `15` (s2) — last swap |
| 2481 | swipe | `3 start (interval 420 s) at 540,1914` |
| 2482 | touch | `0 down at 540,1914 edge` |
| 2483 | event size | `236 sender=0x100000131` |
| 2484 | queue stats | `enq=22 drop=0 type=11 head=5280 tail=5280` |
| 2486,2487,2488,2489,2490,2491,2492,2493 | swipe | `3 move 1/8…8/8 at 540,1764 / 1614 / 1464 / 1314 / 1164 / 1014 / 864 / 714` |
| 2494 | touch | `0 up at 540,714 edge` |
| 2495 | swipe | `3 release at 540,714` |
| 2496 | swipe | `selftest done` (last line containing `SWEET HID: swipe`) |
| 3606 | LAST LINE OF RING | `exec xpcproxy` (`grep -n "" … \| tail -1`) |

Every one of the 31 `swipe`, 8 `swap`, 4 `stats`, 4 `event size`, 8 `touch` lines is listed above (the move
rows carry all 8 line numbers each).

## 3. Touch transitions — `grep -c` / `grep -n` on `SWEET HID: touch`
| metric | ring62 | ring61-true |
|---|---|---|
| `SWEET HID: touch` total | **8** | 36 |
| down / up | **4 / 4** | 18 / 18 |
| `SWEET HID: swipe` | **31** | **0** |

Coordinates in order: `1079,1919↓ / 1079,1919↑` (selftest) · run 1 `540,1914↓ / 540,714↑` · run 2 same ·
run 3 same. **2 touch lines per run** (1 down + 1 up); `python3 -c "print(3*2, 3*2+2)"` → `6 8` = 3 runs +
the control selftest. The 8 moves per run produce `swipe … move n/8` lines, not `touch` lines. VERIFIED.

## 4. Queue lifecycle — `grep -n "SWEET HID: queue stats"`
`python3` over those 4 lines: `line 982: …head==tail=True 240*enq=0` · `1601: …head==tail=True 240*enq=480` ·
`2050: …head==tail=True 240*enq=2880` · `2484: …head==tail=True 240*enq=5280` ·
`enq deltas [2, 10, 10]` · `head deltas [480, 2400, 2400]` · `head==240*enq all: True`.
| # | line | position | enq | drop | type | head | tail | head==tail |
|---|---|---|---|---|---|---|---|---|
| 1 | 982 | pre-swipe, inside selftest (between event-size and touch-up) | 0 | 0 | 0 | 0 | 0 | yes |
| 2 | 1601 | run 1, right after `down` | 2 | 0 | 11 | 480 | 480 | yes |
| 3 | 2050 | run 2, right after `down` | 12 | 0 | 11 | 2880 | 2880 | yes |
| 4 | 2484 | run 3, right after `down` | 22 | 0 | 11 | 5280 | 5280 | yes |
`head == tail` at all 4 samples; `head == 240*enq` exactly (`python3 -c "print(240-236)"` → `4` B of slack per
236 B event); drop=0. enq grows **0 → 2 → 12 → 22** (`python3 -c "print(22-0)"` → `22`), **+10 per run**
(down+8 moves+up). INFERRED: the stats line
prints before the current event is enqueued. **No stats line exists after 2484**, so queue state after run 3
is UNKNOWN. ring61-true contrast: 19 stats lines, last `3689: enq=514 drop=0 type=11 head=9600 tail=9600`.

## 5. `event size=` — `grep -n "SWEET HID: event size="`
**4** lines (981, 1600, 2049, 2483), all `size=236`, all `sender=0x100000131`
(`grep -o "sender=0x[0-9a-f]*" | sort | uniq -c` → `4 sender=0x100000131`).
`python3 -c "print(int('0x100000131',16),int('0x100000126',16),int('0x100000131',16)-int('0x100000126',16))"`
→ `4294967601 4294967590 11`.
| ring | senderID | decimal | count |
|---|---|---|---|
| ring62 | `0x100000131` | 4294967601 | 4 |
| ring61-true | `0x100000131` | 4294967601 | 17 |
| ring57 (T16) | `0x100000126` | 4294967590 | 22 |
Unchanged vs ring61; differs from the T16 value by 11.

## 6. AKS histogram — `SWEET AKS: <proc> sel N` (a literal `grep "SWEET AKS: sel"` finds 0: proc name is in the middle)
| sel | 0 | 7 | 8 | 9 | 10 | 12 | 14 | 17 | 26 | 27 | 31 | 32 | 35 | 102 | 103 | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ring62 | 95 | 98 | 4 | **0** | 65 | **0** | 3 | 511 | 6 | 6 | 2 | 2 | 55 | 1 | 1 | **849** |
| ring61-true | 95 | 99 | 1 | **0** | 63 | **0** | 3 | 619 | 11 | 11 | 2 | 2 | 58 | 1 | 1 | **966** |
`sel 9` = 0 and `sel 12` = 0 (AKS) in **both** rings. Owners: sel 8 = SpringBoard (62: 4, 61: 1); sel 26 =
securityd 2 + SpringBoard (62: 4, 61: 9); sel 27 = securityd 2 + SpringBoard (62: 4, 61: 9); sel 9/12 = none.
Raw (ring62): `SWEET AKS: securityd sel 26 arg0 0 in 3/0 out 0/0 -> 0x0` (1355, 1471); `… sel 27 …` (1358,
1474); `SWEET AKS: SpringBoard sel 26 arg0 2 in 3/0 out 0/0 -> 0x0` (2086, 2106, 2440, 2804);
`SWEET AKS: SpringBoard sel 27 arg0 2 in 2/0 out 0/0 -> 0x0` (2101, 2438, 2443, 2805);
`SWEET AKS: SpringBoard sel 8 arg0 0 in 1/0 out 0/0 -> 0xe00002c7` (2102, 2439, 2444, 2806).
SWEET FB family (not AKS): `MobileGestaltHelper sel 8 in 0/0 out 2/0` (1006), `backboardd sel 12 in 1/0 out
0/0` (1111), `backboardd sel 27 in 0/0 out 0/3084` (1114) — same three in ring61-true (1073, 1626, 1629).

## 7. SpringBoard / backboardd
| metric | count ring62 | ring61-true | lines |
|---|---|---|---|
| `exec SpringBoard` | **1** | 1 | 478 |
| `exec backboardd` | **1** | 1 | 544 |
| `SWEET AKS: SpringBoard` | **44** | 124 | sel list below |
| `SWEET AKS: backboardd` | **3** | 3 | 932 (sel 0), 933 (sel 17), 1074 (sel 17) |
| `SWEET FB: backboardd` | 21 | 21 | AOps callbacks, sels 3,4,5,6,12,15,17,22,27,29,33,50,55,57,68×2,74,79×3,84 |
| all `exec` | **1077** | 757 | — |
Last 5 `SWEET AKS: SpringBoard` (of 44): 2581 sel 17 · 2633 sel 35 · 2804 sel 26 · 2805 sel 27 · 2806 sel 8.
`exec SpringBoard`/`exec backboardd` occur once each → "last 5" is that single line (478 / 544).
All 44 as `line:sel` — 1184:0 1185:35 1186:7 1187:35 1268:17 1269:17 1270:17 1271:17 1348:17 1349:17
1568:17 1569:17 1570:17 1571:35 1575:7 1848:17 2085:32 2086:26 2100:32 2101:27 2102:8 2106:26 2143:17
2145:17 2146:17 2147:17 2152:17 2153:17 2295:35 2307:17 2308:17 2309:17 2310:17 2438:27 2439:8 2440:26
2443:27 2444:8 2580:17 2581:17 2633:35 2804:26 2805:27 2806:8.

## 8. Touch-era sanity (finger/tap path)
| marker | ring62 | ring61-true |
|---|---|---|
| `PRA touch` | **0** | 104 |
| `PRA i2c scan` | **0** | 1 |
| `hid inject` | **0** | 1 (line 266) |
| `reports=` / `errs=` / `corrupt=` | **0 / 0 / 0** | 104 / 104 / 104 |
No touch-driver telemetry exists in ring62 at all, so there are no `reports=`/`errs=`/`corrupt=` values to
quote. Last two ring61-true telemetry lines (`grep -n "PRA touch" work/ring61-true.txt | tail -2`):
```
3639:PRA touch: irq lo/hi=83000/0 idle=0 reports=377 errs=12 corrupt=0 reads=81812 last_len=0 last: slot=0 x=623 y=986 p=159
3695:PRA touch: irq lo/hi=84000/0 idle=0 reports=579 errs=16 corrupt=0 reads=82451 last_len=0 last: slot=0 x=540 y=1265 p=208
```

## 9. Frame / present evidence — `grep -n "SWEET FB: swap"`
Counters `[1, 2, 3, 6, 7, 8, 14, 15]`; highest numeric counter printed = **15** (2436).
| line | 1135 | 1143 | 1191 | 2173 | 2336 | 2337 | 2340 | 2436 |
|---|---|---|---|---|---|---|---|---|
| counter | 1 | 2 | 3 | 6 | 7 | 8 | 14 | 15 |
| surface | 2 | 3 | 2 | 3 | 2 | 3 | 3 | 2 |
Counters are not contiguous (4, 5, 9–13 never printed) → **no frame count claimed**. Last swap **2436**,
last swipe **2496**, last `release` 2495: `python3 -c "print(2496-2436,2495-2436)"` → `60 59` — 60 lines of
ring after the last swap before the last swipe line, and no swap line after 2436. ring61-true: 9 swaps,
counters `1 2 3 6 7 9 11 12 13`.

## 10. Health
| check | result |
|---|---|
| `grep -c panic` | **0** |
| `PRA LOG: strat flush` | **890**; last `3590:PRA LOG: strat flush 128 blocks total=201453 err=0 skipped=0` → last **total=201453**, err=0 skipped=0 |
| `log write fail` (literal) | **0** |
| `PRA LOG: write failed` | **9**, all `35`: 179 (1 tick), 211 (2), 324 (3), 484 (4), 581 (5), 605 (6), 616 (7), 643 (8), 2536 (`after 64 ticks (lock=64 card=0)`); ring61-true also 9, same shape, last 2640 |
| exec loop | `841 xpcproxy`, `9 com.apple.datamigrator`, then `2` each: `watchdogd, usermanagerd, PosterBoard, mount` (1077 exec lines) |
`CRASH` lines: PosterBoard 4, driverkitd 4 — identical counts in ring61-true.

## 11. Anomalies / diffs vs ring61 (facts only)
1. **`PRA touch` channel entirely absent: 0 vs 104 lines** (and `PRA i2c scan` 0 vs 1). Cause VERIFIED in the
   boot-args line the kernel itself received (`boot-args = ` tail, quoted in full):
   - `work/ring62-full.txt:233` — tail **475 B**: `… sweetsample=Setup … pratouchswipe=420
     pratouchselftest=1 pratouchdbg=1`; `pratouch=1` count **0**, `pratouchreset=1` count **0**.
   - `work/ring61-true.txt:260` — tail **484 B**: `… pratouch=1 pratouchreset=1 pratouchdbg=1
     pratouchselftest=1`; no `pratouchswipe`.
   Cross-check from the packaged image itself (`out/pra-xnu.img`, gzip payload at 0x800, sha256 9d32d5f5…):
   cmdline 475 B, `pratouch=1` 0, `pratouchreset=1` 0, `pratouchswipe=420` 1, `pratouchselftest=1` 1,
   `pratouchdbg=1` 1, `pralog=1` 1, `praloglba=794623` 1 — the same reading, independent of the ring.
   **`pratouch=1` and `pratouchreset=1` are missing in ring62; `pratouchswipe=420` is new.** Consequence: the
   0172 probe never ran this boot (no i2c scan, no descriptor read, no 10 ms poll), so the user's own taps
   produced nothing BY CONSTRUCTION; only the 3 synthetic swipes are evidence from T20. The swipe still fired
   because 0196 arms its timer unconditionally in `SweetHIDTouch::start()`, while `pratouch` is parsed only in
   the 0172 probe (`xnu/patches/0172-pra-touch-probe.patch:886`).
   NOT evidence either way: the local `xnu-src/` tree is un-patched (it holds `SweetHID.cpp` but contains no
   `PRA touch` string; the pra_touch driver lives only in the patch stack, 0172/0177–0189), so a tree grep
   says nothing about what the T20 kernel contained.
2. `enq` reached **22** vs **514** (23.36× fewer: `python3 -c "print(514/22)"` → `23.363636363636363`); the 22
   = 3 runs × 10 + 2 selftest. `SWEET HID: swipe` 0 → 31.
3. AKS total 966 → 849, SpringBoard AKS 124 → 44, `sel 17` 619 → 511; `sel 9`/`sel 12` still 0; SpringBoard
   `sel 8` still returns `0xe00002c7`.
4. `exec` total 757 → 1077, driven by `xpcproxy` 757 → 841.
5. Swipe spacing **UNKNOWN**: only 5 `[+ N s]` lines exist (`grep -c "^\[+ "` → 5, all `[+ 30 s]`, lines 2–12);
   nothing near 1598/2047/2481 carries a timestamp. The start lines carry only `(interval 420 s)`.
6. Queue sampled 19× → 4×, last sample at run 3's `down`; `head==tail` and `drop=0` hold at every sample.
7. No new marker family appears in ring62 (tag census diff shows only per-process names, e.g. `exec
   ASPCarryLog`, `exec betaenrollmentd`, `exec healthappd` ×1; missing = `PRA touch`, `PRA i2c scan`,
   `exec UARPUpdaterService*`).
8. `SWEET HID: queue mapped/notify armed by SweetHIDTouch|SweetHIDButtons` present in both (ring62 977, 978,
   996, 997, 1002, 1003; ring61-true 1001, 1002, 1049, 1050, 1055, 1056).
9. `SWEET FB: display on` occurs **twice** in ring62 (1110, 2171) and the
   second one is followed by the same triple as the first: `SWEET FB:
   backboardd sel 79 in 2/0 out 0/40` then `SWEET FB: swap 6`. ring61-true has
   the same two lines (1625, 2533) with the same triple at 2533-2535 — and
   ring61 has 0 swipe lines — so this burst is a recurring boot pattern, not a
   reaction to any gesture. It is the only display-on evidence in either ring;
   there are no `display off` lines in either.

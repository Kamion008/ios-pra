# EVIDENCE 2 — ring measurements (primary, from strings/xxd/cmp runs, 2026-11-17)

All rings: the gitignored ring artifact files, pulled from TWRP via
`adb exec-out 'dd if=/dev/block/mmcblk0 bs=512 skip=794623 count=8193'`
(4,194,816 bytes). The first 512 bytes = the pralog header sector (LBA 794623).
Header layout (pra_sdhci.c:1227-1234): magic[8] "PRALOG1\0", version u32 @8,
size u32 @12, total u64 @16, seq u64 @24. The header is rewritten ONLY by a
fully successful flusher tick (pra_sdhci.c:1226-1238). PRA_LOG_SIZE = 4 MiB
(0x400000), PRA_LOG_SECTORS = 8193 (:210-211). Flusher tick = tsleep(hz*10)
= 10 s (:1201). EBUSY = 16 (bsd/sys/errno.h:108). Ring bytes beyond `total` =
stale fragments of older boots (the flusher writes blocks 0..total/512 from
the window start; older content survives only beyond the written range).

## Boot/ring provenance (work/boots.md rows)

| ring | pulled after | boot outcome | header total | header seq |
|---|---|---|---|---|
| ring34 | the wedged pre-series boot (2026-11-16; black screen, never reached lock screen) | n | 284,020 (0x45574) | 67 (0x43) |
| ring35 | boot #1 2026-11-17 (healthy: lock screen at 8m30s) | y | 209,077 (0x330b5) | 9 |
| ring36 | boot #2 2026-11-17 (healthy, user: "same as boot 1") | y | = ring35 | = ring35 |
| ring37 | boot #3 2026-11-17 (healthy, user: "same as boot 2") | y | = ring35 | = ring35 |

`cmp ring35 ring36`: NO output (byte-identical). `cmp ring35 ring37`: NO
output (byte-identical). sha256 first-16 of all three: 9316b9ce5ffd7289.

## ring34 (wedged boot) facts

- "PRA LOG: write failed" lines: 29. The "after N ticks" sequence: 1,2,3,4,
  5,6,7,8 (early boot), then ONE line "after 64 ticks", then the counter
  RESETS (later "after 1", "after 2" lines) — a reset requires a fully
  successful flush in between (pra_sdhci.c:1252-1254).
- "PRA LOG: strat flush" lines: 0 — strat's own evidence flush never fired.
- Mutex parks in the FRESH region (byte offsets < 284,020; `strings -t d`):
    36,149  SMP backboardd t0 ... st=0x9 we=0xfffffff00844dc08 ...
   136,813  SMP SpringBoard t10 ... st=0x9 we=0xfffffff00844dc08 ...
   168,476  SMP launchd t2 ... st=0x9 we=0xfffffff00844dc08 ...
  (st=0x9 = TH_WAIT|TH_UNINT. we= the mutex state-word address; the ring
  parsing rules treat >=3 distinct threads on the SAME we across repeated
  samples as a trusted park.)
- Header seq=67: the flusher completed 67 fully-successful flush ticks in
  this boot — it acquired the lock and wrote to disk repeatedly WHILE the
  parks above were present in the fresh region.

## ring35 (healthy boot #1) facts

- "PRA LOG: write failed" lines: 53; observed counts "after 1/2 ticks"
  (short bursts). Byte offsets 11,585 / 13,282 / 30,469 are INSIDE the fresh
  region (< 209,077); offsets 283,486 / 285,088 / 295,934 are BEYOND total =
  stale fragments of older boots.
- Mutex parks INSIDE the fresh region (a HEALTHY boot parked threads on the
  mutex too — these resolved; boot #1 reached the lock screen):
    36,227  SMP backboardd t0 ... we=0xfffffff00844dc08 ...
    37,642  SMP launchd t4 ... we=0xfffffff00844dc08 ...
    51,697  SMP launchd t0 ... we=0xfffffff00844dc08 ...
   131,479  SMP launchd t0 ... we=0xfffffff00844dc08 ...
- Header: seq=9 successful flush ticks for the whole boot (~90 active 10-s
  ticks before the sampler's 90-sample cap ends new content; sampler cap is
  a stated fact in HANDOFF_2026-11-16-c.md section 2).
- Init line "PRA LOG: lba=794623, 8193 sectors, idle=0 at=0" is present.

## The conflation that limits the ring evidence (pra_sdhci.c:1087-1091)

"write failed 16" is printed for the flusher's PER-SECTOR failure, but the
EBUSY can come from TWO sources the line does not distinguish:

 1087		if (!lck_mtx_try_lock(&pra_emmc_lock)) {
 1088			return EBUSY;
 1090		error = pra_emmc_write_raw(lba, sector);

:1088 = lock busy; :1090 = card-side errors also surface from write_raw.
So a starvation window ("after 64 ticks") can be lock-EBUSY, card-EBUSY, or
both; the ring alone cannot tell them apart.

## APPEND (2026-11-17 evening — measured after the packet was first built)

### ring34's full write-failure offset table (strings -a -t d, 29 lines)
  10,270 / 12,940 / 20,246 / 30,256 / 31,686 / 32,445 / 33,820 / 34,675
  (the "after 1..8 ticks" early burst — all INSIDE fresh < 284,020),
 175,611 (the single "after 64 ticks" line),
 195,731 / 196,221 / 197,566 / 207,252 / 207,742 (after 1-5),
 209,606 / 210,772 / 211,589 / 212,430 / 213,144 / 213,463 / 217,495 (1-7),
 228,312 / 238,973 / 239,556 / 251,344 (1), 282,337 / 283,150 / 283,897 /
 284,387 (1, 1, 1, 2) — note: 284,387 lies BEYOND total=284,020, so that
 line is a stale fragment of an OLDER boot, not this boot's content; the
 wedged boot's own failure lines end at 283,897 (< total).
The 64-tick window (175,611) sits AFTER the park lines (36,149 / 136,813 /
168,476) with ZERO failure lines between 34,675 and 175,611.

### ring38 (boot #4, healthy, clock 4:07)
sha256 first-16 = 9316b9ce5ffd7289 — BYTE-IDENTICAL to ring35 (cmp empty);
header total/seq = 209,077 / 9 (boot #4 wrote NOTHING).

### ring39 (boot #5, healthy, clock 4:07)
sha256 first-16 = bb29d0ef3994b45e — DIFFERS from ring35. Header:
total=133,205 (0x20855), seq=2 (only TWO fully-successful flush ticks).
"write failed" lines: 43; early ones at 13,077-30,343 INSIDE fresh; offsets
283,486 / 285,088 / 295,934 are BEYOND total (stale boot-#1-era fragments).
"strat flush" lines: 0.
Mutex parks INSIDE fresh: 52,502 (launchd t3), 87,912 (launchd t0),
130,509 (launchd t3) — all we=0xfffffff00844dc08.
PER-THREAD TIMELINE (the park-persistence probe): launchd t3,
th=0xfffffff54bb5dc00, appears exactly 3 times: st=0x9 @52,502, st=0x1
@88,571, st=0x9 @130,509 — the park RESOLVED (the thread got in, ran, and
re-parked on a later sync cycle). st=0x1 = TH_WAIT without TH_UNINT.

### Interpretive impact of ring39
Healthy boots now form a starvation SPECTRUM: successful flush ticks out of
~90 active ticks = 0 (boots #2/#3/#4), 2 (boot #5), 9 (boot #1); and the
wedged boot = 67 (its parks/EBUSY pattern differs — see the offset table
above). Parks on the mutex occur in EVERY measured healthy boot and RESOLVE
(the th= timeline). The wedged boot's TERMINAL park state was never flushed
(self-erasing evidence: content stops at the last successful flush).


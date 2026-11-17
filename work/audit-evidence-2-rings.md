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

# AUDIT — pra_emmc_lock wedge + stale-ring mechanism (2026-11-17)

author: GLM-5.3-Flash (ZCode session 2026-11-17); evidence = CI run
44119547672 buildtree (the source 0175-era CI compiled), rings 34-39,
nm on the 0175 CI kernel. Claim + hostile reviews: work/claim-wedge-diagnosis.md
(v2), work/pkt-173719 (blind pass), work/pkt-175415 (claim round 1),
work/pkt-182616 (claim round 2: 1 refuted / 10 weak / 5 survive).

## Mechanism (current state of belief)

- VERIFIED in source: strat holds pra_emmc_lock across its ENTIRE request
  loop (pra_sdhci.c:2381 -> :2506, no returns/gotos inside; confirmed by
  review round 2 C1a). Every IO poll is bounded (init 4,000,000 iterations;
  command polls 2,000,000 — wall time per failed poll UNKNOWN, order
  0.1-0.5 s INFERRED from the bound).
- VERIFIED in rings: starvation spectrum across healthy boots — successful
  flush ticks of ~90 active: 0 (boots #2/#3/#4), 2 (#5), 9 (#1); the wedged
  boot managed 67 with one 64-tick (>=640 s) EBUSY window that is a MID-BOOT
  TRANSIENT (counter resets after it — review round 2 C1c refuted its use
  as a terminal-wedge signature). Parks on the mutex (we=_pra_emmc_lock+0x8,
  nm-verified = 0xfffffff00844dc00 + 8) occur in every measured boot and
  resolve in the healthy ones (ring39 th=0xfffffff54bb5dc00: st=0x9 ->
  st=0x1 -> st=0x9 — the thread LEFT the mutex wait and moved to another
  wait event; st=0x1 is TH_WAIT, not run state).
- The wedge's TERMINAL park state was never flushed (content stops at the
  last successful flush; the "write failed" lines live in the RAM ring and
  reach disk only on a later success — self-erasing evidence). Whether the
  terminal wedge is (a) a stuck/never-completing holder or (b) turnstile
  waiters never woken is INSUFFICIENT from rings — the 0176 instrument
  decides: data + tsid + decoded owner, printed from INSIDE the locked
  region (the console is the guaranteed capture channel there; disk copy
  follows when the lock frees).
- Structure: try_lock CASes the 32-bit data word against 0 and ignores
  queues (lock_mtx.c:1126-1133); waiters hang off the TURNSTILE
  (lck_mtx_tsid -> waitq_wakeup64_one, assert(did_wake==KERN_SUCCESS)) —
  data==0 does not mean "no waiters". Panic-path steal (:1461) has exactly
  one caller (debug.c:1464-1467); the patch stack never touched the lock
  machinery (0124 = CNTP/CNTV timer registers only).

## Review outcome ledger (survived / revised / abandoned)

Blind pass (pkt-173719): independently converged on starvation-behind-slow-
requests; STRONG-refuted the steal; named the self-erasing-evidence prop-
erty; separators = owner/request logging + state dump + per-boot nonce ->
all adopted into the 0176 design.

Claim round 1 (pkt-175415): C1 "VERIFIED" overclaim -> REVISED (EBUSY
conflation). Packet-stale items (boots #4-#6, ring38/39, offset tables) ->
REVISED into evidence-2/3 append. "640 s" -> REVISED to >=640 s. Nested
double-acquire hazard -> REJECTED with caller analysis (evidence-4: only
callers of pra_log_write_sector are :1222/:1237 in pra_log_thread;
strat_flush -> flush_locked -> write_raw directly). 0124 characterization
-> REVISED with the hunk excerpt (evidence-4). review.sh claim-root bug
found by the round-1 refusal -> FIXED (claim.md now copied to packet root).

Claim round 2 (pkt-182616): C1c REFUTED (the 64-tick window is a mid-boot
transient, not terminal) -> ACCEPTED, claim revised. C1d "every poll <=2M"
-> REVISED (init loop is 4M; the 1-2 s comment is the log path's). C2a
st=0x1 is TH_WAIT not run -> REVISED wording (the thread LEFT the mutex
wait; what it did between samples is not proven). C2c falsifier wording ->
REVISED (tsid==0 while parks persist = the queue dissolved without waking
= deeper-than-(b); (b) itself = tsid!=0 + no wake). C3 grep listing ->
ACCEPTED (added to evidence-3); caveat reworded (a FAILED panic flush
leaves the prior header; a successful one writes a new one). C4a list
phrasing -> REVISED (17 patches = the FULL grep list; none after 0166
mentions lck_mtx). C4b kernel-vs-image identity -> ACCEPTED (pre-series
boots ran the same flashed 0175 image, handoff sec 1/8). C5-1 FAULT catch
(the error break at :2500-2502 would exit a naive lock-at-top placement
with the lock held across buf_unmap) -> ACCEPTED as a 0176 generator
constraint: lock/unlock PER ITERATION with the error check inside the
locked section. C5-2 capture channel -> ACCEPTED (console + RAM ring are
the guaranteed channels under the lock; disk follows later). C5-3 header
invariant -> ACCEPTED: 0176's strat tail-flush writes NO header (or a
partial-flagged one) — the measured rings' accounting relies on "header
total = fully-flushed boundary", and strat's 128-block tail + header
write would break it (strat flush count = 0 in all measured rings, so no
measured ring is affected). C5-4 stale packet -> boots.md rows 4-6 now
carry the clock data. The 1.92-vs-19.2 MHz limiter arithmetic -> OPEN
QUESTION recorded; 0176 limiters are COUNT/TICK-based.

## 0176 design (as constrained by the audit)

1. per-iteration lock/unlock in strat's request loop (lock -> sector/chunk
   work incl. shared-buffer copies -> unlock -> error check/break OUTSIDE).
   Effect: every hold bounded to one sector/chunk; flusher + waiters
   interleave; a stuck-card request degrades to slow IO. Removes the
   strat-hold confounder from the wake-path measurement; NOT claimed to
   fix fork-(b).
2. telemetry INSIDE the locked region, rate-limited by COUNT: hold-time
   line (lba/count), mutex data + tsid + decoded owner
   (ctid_get_thread_unsafe, extern at thread.h:1643), distinct lock-busy
   vs card-busy return codes in pra_log_write_sector.
3. strat tail-flush INSIDE the locked region before unlock, COUNT-limited,
   NO header write (evidence invariant preserved).
4. clock_get_calendar_microtime next to mach_absolute_time in the sampler
   header (exception.c:1021 region) — measures the real timebase scale
   against the calendar, settling the limiter question too.

## Open items

- The timebase scale (1.92 vs 19.2 MHz) — the 0176 clock line measures it.
- Whether the terminal wedge is fork-(a) or (b) — the 0176 telemetry
  during a wedged boot decides (a wedged boot with 0176 is the money
  sample; pull its ring BEFORE any power cycle).
- Touch: 0177 subagent in flight (rung A reset + rung B injection +
  pra_i2c arbitration); the IC has NACKed on every boot so far — rail
  enable offsets UNKNOWN (design note sec 2/6).
- Boot #6 ring40 + row pending (phone was in XNU at last check).

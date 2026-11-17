# CLAIM v2: the _pra_emmc_lock wedge + the stale-ring mechanism

author: GLM-5.3-Flash (ZCode session 2026-11-17; commits 189fd5a..; evidence
= work/audit-evidence-1/2/3/4, CI run 44119547672 buildtree, rings 34-39)
Revised after claim review round 1 (work/pkt-175415/report.md): C1 softened
(EBUSY conflation), packet-stale items refreshed (boots #4-#6, ring38/39),
hold-time numbers bounded honestly, telemetry moved inside the locked
region, strat-flush contract fixed, the 1.92-vs-19.2 MHz limiter question
recorded as open.

## C1 — strat's whole-request hold is the contention unit (mechanism
## VERIFIED in source; the ring attribution of EBUSY windows to the lock is
## INFERRED and waits on 0176 telemetry)

strat holds pra_emmc_lock from lck_mtx_lock (pra_sdhci.c:2381) to
lck_mtx_unlock (:2506) — the ENTIRE per-sector request loop (source excerpt,
evidence-1). Every bounded poll is <=2,000,000 register reads, an UPPER
bound whose wall time is UNKNOWN (order 0.1-0.5 s INFERRED from the bound;
the "~1-2 s" figure in the source comment describes the LOG write path,
evidence-1:1333-1334, not strat). Ring attribution limit: "write failed 16"
covers BOTH lock-EBUSY (:1088) and card-side errors (:1090) — the ring
cannot separate them (evidence-2 conflation section). What the rings DO
establish: a starvation spectrum across healthy boots (successful flush
ticks out of ~90 active: 0, 0, 0, 2, 9 — evidence-2 append) with one
window in the wedged boot spanning >=640 s (64 failing ticks at the 10 s
cadence; >=, not =, because the counter only resets on success,
evidence-1:1252-1254), and the offset table (evidence-2 append) placing
that window AFTER the recorded parks. FALSIFIER: 0176 telemetry showing
sub-10-s-equivalent strat holds during starvation windows.

## C2 — parks resolve in healthy boots; the wedge's terminal state is
## unflushed, so lost-wakeup vs stuck-holder is INSUFFICIENT from rings

Parks on the mutex occur in every measured boot and RESOLVE: ring39's
launchd t3 timeline is st=0x9 @52,502 -> st=0x1 @88,571 -> st=0x9 @130,509
(evidence-2 append) — park, run, re-park: the strat-hold queueing rhythm.
Structurally, parks can coexist with successful try_locks because try_lock
CASes the 32-bit data word against 0 while waiters hang off the TURNSTILE
(lck_mtx.c:1126-1133 and :616-641, evidence-4) — data==0 does not mean "no
waiters". The wedged boot's TERMINAL park state was never flushed (content
stops at the last successful flush, total=284,020; self-erasing evidence).
Therefore: whether the terminal wedge is (a) a stuck/never-completing
holder, (b) turnstile waiters never woken, or (c) both in sequence, CANNOT
be decided from rings — INSUFFICIENT. The 0176 instrument decides it:
print data + tsid + the decoded owner thread from INSIDE the locked
region. FALSIFIERS: telemetry showing tsid==0 while parks persist
(b refuted), or owner==0 + data==0 with parks persisting (neither a nor b
— something else).

## C3 — the panic-path steal is not involved (SURVIVES review round 1)

pra_log_panic_flush's opaque[1] zeroing (:1461) has exactly one caller:
osfmk/kern/debug.c:1464-1467, the panic hook (evidence-3/4). Caveat kept
honest: "no panic occurred" is INFERRED — a FAILED panic flush leaves the
same stale header the success path writes; nothing in the rings shows a
panic signature for these boots.

## C4 — the patch stack never touched the lock machinery (VERIFIED)

grep over xnu/patches/*.patch: every lck_mtx mention is driver/console
files; no patch touches osfmk/kern/locks* / machine locks (evidence-3).
0124's machine_routines.c hunk is CNTP/CNTV timer-register selection only
(evidence-4 carries the hunk excerpt). The lock implementation is stock
xnu-8796.141.3. The park event address is script-verified as the driver's
own mutex: nm gives `fffffff00844dc00 b _pra_emmc_lock` = we − 0x8
(evidence-3/4).

## C5 — the 0176 change set (one branch of a declared fork, plus the
## instrument that settles the fork)

1. per-sector lock scoping in strat's request loop (move :2381/:2506 inside
   the loop; the shared pra_emmc_bounce / pra_emmc_multi_buf read+copy
   stays inside each critical section). Effect: every hold is bounded to
   one sector/chunk — the flusher and parked waiters interleave, and a
   slow/stuck-card request degrades to slow progress instead of a
   system-wide wedge (the terminal-wedge shape becomes structurally
   impossible from this driver). Under fork-(b) (pure lost wakeup) this
   alone does not restore wakeups — it is NOT claimed as the wedge fix; it
   removes the strat-hold confounder so the telemetry measures the wake
   path cleanly, and it caps the damage of fork-(a).
2. telemetry INSIDE the locked region (a stuck holder self-reports before
   any unlock exists to flush): rate-limited hold-time line with lba/count,
   the mutex state word + tsid + the decoded owner thread
   (ctid_get_thread_unsafe — extern at osfmk/kern/thread.h:1643, evidence-4),
   and DISTINCT return codes for lock-busy vs card-busy in
   pra_log_write_sector (kills the evidence-2 conflation). Limiters are
   TICK/COUNT-based, not mach_absolute_time deltas, because the timebase
   scale is an OPEN question: the existing :1408 constant 10ULL*1920000ULL
   means 10 s only at 1.92 MHz and 1 s at 19.2 MHz (review round 1, valid
   arithmetic objection — unverified either way; the 0176 clock line
   measures the real scale).
3. strat flushes the ring tail INSIDE the locked region immediately before
   :2506 (honors the documented "called with pra_emmc_lock held" contract —
   review round 1's FAULT objection accepted), rate-limited by request
   COUNT. This gives disk coverage in the parks/free-lock regime; in a
   stuck-holder regime the item-2 in-locked telemetry self-reports.
4. clock_get_calendar_microtime next to mach_absolute_time in the sampler
   header (H2 discriminator; never-redrawn leads after boots #4-#5's 4:07
   and boot #6's 4:08).

## Rebuttal on the record (review round 1, rejected objection)

The hypothesized nested double-acquire (strat -> pra_log_strat_flush ->
pra_log_write_sector -> try_lock while strat holds the lock) cannot occur:
pra_log_write_sector's only callers are pra_sdhci.c:1222 and :1237, both in
pra_log_thread; pra_log_strat_flush calls pra_log_flush_locked, which calls
pra_emmc_write_raw directly (:1353/:1366) — evidence-4 carries the caller
analysis.

## What would falsify this claim set

0176 telemetry during a wedge showing tsid==0 + data==0 while parks persist
(the queue dissolved without waking anyone — deeper than fork-(b)), or
sub-10-s-equivalent strat holds during starvation windows with the flusher
failing on card-side errors only — either moves the diagnosis off C1/C5.

## ADDENDUM — claim review round 2 (work/pkt-182616): 1 refuted / 10 weak /
## 5 survive; revisions adopted

- C1c REFUTED: the 64-tick window is a MID-BOOT TRANSIENT (counter resets
  at 195,731-217,495 prove successful flushes after it) — it is NOT a
  terminal-wedge signature. C1 no longer leans on it.
- C1d: poll bounds stated per-loop-class (init 4,000,000; commands 2,000,000);
  the "~1-2 s" figure belongs to the LOG path's comment; wall time per
  failed poll stays UNKNOWN/INFERRED.
- C2a: st=0x1 is TH_WAIT (not run) — the timeline proves the thread LEFT
  the mutex wait and reached a different wait event, nothing more.
- C2c falsifier wording: (b) = tsid!=0 with no wake; "tsid==0 while parks
  persist" = the queue dissolved without waking anyone = deeper than (b).
- C3: "no panic occurred" is INFERRED (a FAILED panic flush leaves the
  prior header; a successful one would write a new one). The grep listing
  for pra_log_panic_flush is in evidence-3/4.
- C4: the 17-patch list is the FULL grep output (none after 0166 mentions
  lck_mtx); the pre-series boots ran the same flashed 0175 image (handoff
  sec 1/8), so the nm address applies to ring34's boot too.
- C5 constraints adopted (see work/audit-pra-emmc-lock-2026-11-17.md):
  per-iteration lock/unlock (the :2500-2502 error break must not exit
  holding the lock), COUNT/TICK-based limiters (the :1408 timebase
  constant is unverified), strat tail-flush writes NO header (the
  header/total invariant stays intact), console+RAM-ring are the
  guaranteed telemetry channels under the lock.


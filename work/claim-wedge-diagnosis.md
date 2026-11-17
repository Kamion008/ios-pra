# CLAIM: the _pra_emmc_lock wedge + the stale-ring mechanism (post-blind-pass)

author: GLM-5.3-Flash (ZCode session 2026-11-17; commits 189fd5a/9d71e91 +
this claim's commit; evidence = work/audit-evidence-1/2/3, CI run 44119547672
buildtree, rings 34-38)

## C1 — strat's whole-request hold starves the flusher (VERIFIED mechanism)

strat holds pra_emmc_lock from lck_mtx_lock (pra_sdhci.c:2381) to
lck_mtx_unlock (:2506) — the ENTIRE per-sector request loop, including
bounded 2,000,000-iteration register polls per sector. Consequences measured
in the rings: the wedged boot's flusher hit one 64-tick (640 s at the 10 s
tick, pra_sdhci.c:1201) EBUSY window ("write failed 16 after 64 ticks", byte
offset 175,611 in ring34) and boot #1 (healthy) succeeded only 9 times in
~90 active ticks with 53 complaint lines. The user corroborates the
write-failed signature as pre-existing and "temporary on most boots" —
transient windows resolve with a success (which is also the only way the
lines reach disk), so a boot-long storm leaves byte-identical stale rings
and no trace (boots #2/#3/#4: cmp vs ring35 empty, seq frozen at 9).
FALSIFIER: 0176 telemetry showing sub-10 s strat holds during starvation.

## C2 — the wedge parks are NOT explained by a continuous holder

ring34: parks at bytes 36,149 (backboardd t0), 136,813 (SpringBoard t10),
168,476 (launchd t2) — ALL before the 64-tick window (175,611), with ZERO
write-failure lines between bytes 34,675 and 175,611: the flusher acquired
the lock repeatedly WHILE three threads sat parked on the mutex. ring35
(healthy boot) parks at 36,227/37,642/51,697/131,479 inside its fresh
region. Structurally possible WITHOUT corruption: lck_mtx_try_lock does a
raw CAS of the 32-bit lck_mtx.data word against 0, deliberately ignoring
queues (osfmk/kern/lock_mtx.c:1126-1133), and parked waiters hang off the
TURNSTILE (lck_mtx_tsid -> turnstile -> waitq_wakeup64_one in
lck_mtx_unlock_wakeup, lock_mtx.c:616-641) — so data==0 does not imply "no
waiters". Two live mechanisms remain, separated ONLY by the 0176 state
telemetry: (a) turnstile-enqueued waiters that no unlock ever wakes (lost
wakeup: tsid set, data==0, parks persist); (b) parks that are short and
merely caught by the sampler (they resolve; the terminal wedge state was
never flushed — self-erasing evidence ends at ring34's total=284,020).
FALSIFIER for (a): 0176 prints tsid==0 at moments when parks persist.

## C3 — the panic-path steal is not involved (VERIFIED)

pra_log_panic_flush's opaque[1] zeroing (:1461) has exactly one caller:
osfmk/kern/debug.c:1464-1467, the panic hook. No panic occurred in any
measured boot. The flusher's 67 successful ticks in the wedged boot also
coexist with balanced driver lock sites (no returns/gotos inside the locked
region) and zero interrupt-context acquires (polled PIO, lock-free
_cnputc path).

## C4 — the patch stack never touched the lock machinery (VERIFIED)

grep over xnu/patches/*.patch: every lck_mtx mention is in driver/console
files; no patch touches osfmk/kern/locks* / machine locks. 0124's
machine_routines.c hunk = CNTP/CNTV physical-timer selection only (no
wfe/sev/idle changes). The lock implementation is stock xnu-8796.141.3
(osfmk/kern/lock_mtx.c, MCS/turnstile design).

## C5 — the fix set for 0176

1. per-sector lock scoping in strat's request loop (move :2381/:2506 inside
   the loop, keeping the shared pra_emmc_bounce / pra_emmc_multi_buf
   read+copy inside each critical section): bounds every hold to one
   sector/chunk — the flusher and parked waiters interleave; a slow-card
   request degrades to slow progress instead of a system-wide wedge.
2. H1 telemetry, rate-limited: at the flusher's repeated try_lock failures,
   print the mutex state word AND tsid AND the decoded owner thread
   (ctid_get_thread_unsafe on data, as lck_mtx.c's own
   LCK_MTX_OWNER_FOR_TRACE does); at strat unlock, a >10 s hold line
   (lba/count/duration); disambiguate flusher EBUSY (lock-busy vs card-busy
   return codes). Interpretation per handoff section 4 H1.
3. strat flushes the ring tail at unlock, rate-limited to 10 s (the limiter
   already exists at :1408) — guarantees disk coverage when the thread
   flusher starves, and carries the flusher counters in the header.
4. clock_get_calendar_microtime next to mach_absolute_time in the sampler
   header (H2 discriminator; never-redrawn currently leads after boot #4's
   4:07-vs-4:08).

## What would falsify this whole claim

0176 telemetry during a wedge showing tsid==0 + data==0 while parks persist
(a wake path that never enqueued), or strat holds < 10 s throughout with the
flusher succeeding every tick — either would move the diagnosis off C1/C2.

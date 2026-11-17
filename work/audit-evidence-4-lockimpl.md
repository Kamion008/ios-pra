# EVIDENCE 4 — the stock mutex implementation + rebuttal data (2026-11-17 evening)

Source: CI run 44119547672 buildtree, osfmk/kern/lock_mtx.c (1421 lines) —
the stock xnu-8796.141.3 mutex implementation (MCS/turnstile design; no
patch in the stack touches this file — see evidence-3).

## try_lock CASes the 32-bit data word against 0, ignoring queues

 1111	static __attribute__((always_inline)) bool
 1112	lck_mtx_try_lock_fastpath(lck_mtx_t *lock, lck_mtx_mode_t mode)
 1113	{
 1114		thread_t thread = current_thread();
 1115		uint32_t odata, ndata = thread->ctid;
 1116		uint32_t take_slowpath = 0;
 ...
 1126		/*
 1127		 * try_lock because it's likely to be used for cases
 1128		 * like lock inversion resolutions tries a bit harder
 1129		 * than lck_mtx_lock() to take the lock and ignores
 1130		 * adaptive spin / interlock queues by doing the CAS
 1131		 * on the 32bit mutex data only.
 1132		 */
 1133		lock_cmpxchgv(&lock->lck_mtx.data, 0, ndata, &odata, acquire);

Implication: try_lock succeeds whenever data==0 — parked waiters do NOT
live in `data`, so "try_lock succeeds" does not mean "no waiters exist".

## The wakeup path is turnstile-based and asserts success

 616 (lck_mtx_unlock_wakeup)
 631		ts = turnstile_get_by_id(lck->lck_mtx_tsid);
 ...
 638		did_wake = waitq_wakeup64_one(&ts->ts_waitq, LCK_MTX_EVENT(lck),
 639		    THREAD_AWAKENED, WAITQ_UPDATE_INHERITOR);
 640		assert(did_wake == KERN_SUCCESS);

Waiters are enqueued on a turnstile reached via lck_mtx_tsid; a failed wake
panics (DEVELOPMENT kernel assert) rather than silently dropping.

## The owner is decodable from the state word

 647	static inline bool
 648	lck_mtx_ctid_on_core(uint32_t ctid)
 649	{
 650		thread_t th = ctid_get_thread_unsafe(ctid);
 ...
 654	#define LCK_MTX_OWNER_FOR_TRACE(lock) \
 655		VM_KERNEL_UNSLIDE_OR_PERM(ctid_get_thread_unsafe((lock)->lck_mtx.data))

and osfmk/kern/thread.h:1643: `extern thread_t ctid_get_thread_unsafe(ctid_t
ctid);` — the 0176 telemetry can decode the owner thread from data from
bsd/dev (evidence-3 carries the extern line).

## 0124's machine_routines.c hunk (the only CPU-path change in the stack)

The hunk adds A5_USE_PHYS_TIMER-conditional CNTP_TVAL_EL0 / CNTP_CTL_EL0 /
CNTV_CTL_EL0 register accesses (physical-vs-virtual timer selection for the
donor A5). No wfe/sev/wfi/idle-path changes (grep over the hunk: 0 hits).

## Rebuttal data for the review's "nested strat flush" hazard

The review hypothesized strat calling pra_log_strat_flush -> ... ->
pra_log_write_sector -> try_lock while strat already holds the lock (a
double-acquire that would free a foreign mutex at :2506). Caller analysis
(grep over the buildtree file): pra_log_write_sector has exactly TWO
callers — pra_sdhci.c:1222 and :1237, both inside pra_log_thread (the
periodic flusher). pra_log_strat_flush (:1386) calls pra_log_flush_locked
(:1337), which calls pra_emmc_write_raw DIRECTLY (:1353, :1366) — it never
passes through pra_log_write_sector. The nested double-acquire cannot
occur with the current call graph.

## nm check on the 0175 CI kernel (run 43958048368 artifact)

  fffffff00889aa20 s ___startup_lck_mtx_spec_pra_emmc_lock
  fffffff00844dc00 b _pra_emmc_lock

we=0xfffffff00844dc08 (the park event address in rings 34/35/39) =
_pra_emmc_lock + 0x8 exactly.

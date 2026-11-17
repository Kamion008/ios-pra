# Predictions — 2026-11-17 (from boot #3 on; boots 1-2 ran unpredicted)

Committed BEFORE any further boot. Labels: VERIFIED = command output or
file:line; INFERRED marked; anything else UNKNOWN.

## Scope
- Baseline series continues: kernel 0175, image sha 29512a04dba33d8a5281
  (VERIFIED pre-flight readback this session), tweaked root, frozen build.
- 0176 series starts only after 0176 is flashed (own series; never pooled
  with baseline rows).

## Baseline predictions (boots #3+)
- P1 wedge rate: each boot wedges with ~1/3 probability (basis: 1 wedge in
  the 3 pre-series boots, handoff §1; boots #1-2 healthy). The 8-10 boot
  series measures the true rate. FALSIFIER for the wedge IDENTIFICATION:
  a wedged ring WITHOUT the known signature (we=_pra_emmc_lock+0x8,
  launchd sync + backboardd, st=0x9 UNINT — handoff §2) = a different
  wedge mode; re-open.
- P2 clock: the lock-screen clock reads 4:08 at any observable uptime.
  Both open H2 branches (FROZEN gettimeofday, NEVER-REDRAWN label) predict
  this — only the 0176 sampler line separates them. FALSIFIER: clock
  != 4:08 at ~10-15 min uptime.
- P3 render: lock screen static after ~5 presents; "display-off request
  ignored (keep_on)" may appear at the idle timer (benign;
  work/milestone-lockscreen.md).
- P4 IF wedged: the flusher keeps ticking (stats + ring writes continue,
  handoff §2).
- P5 THE RING ANOMALY (new 2026-11-17): boot #2 wrote NOTHING to the ring
  window — ring36 byte-identical to ring35 (sha 9316b9ce, VERIFIED), while
  boot #1 rewrote it (cmp ring34/ring35 diverges byte 17, VERIFIED).
  After-window probe = ANDROID! magic at LBA 802816 (VERIFIED): no ring
  space past the window, so NOT an append. Candidates: (a) the flusher/
  ring-writer thread never started or died early in boot #2 (boot
  otherwise healthy), (b) its writes failed silently. UNKNOWN until boot
  #3's ring: fresh content = stochastic one-off; again identical = the
  writer is broken. NOTE: a healthy boot does NOT guarantee a usable ring;
  record ring presence per boot.

## 0176 series predictions (first boots after flash)
- T1 IF a boot wedges: the >10 s contention telemetry fires with the mutex
  state word + waiter pointers + flusher duty cycle. Interpretation
  (handoff §4 H1): LOW duty + long wait -> lost wakeup / bad lock state;
  ~100% duty -> starvation / hold-across-sleep; waiters flagged + no owner
  -> lost wakeup; garbage state -> corruption. Each names a different fix.
- T2 clock: the sampler header shows clock_get_calendar_microtime next to
  mach_absolute_time; expected wall value = the 1969-12-31 epoch + ~488 s
  (= 4:08 PM) held constant across samples if gettimeofday is frozen;
  advancing = conversion works; constant-but-wrong = scale/seed bug.
- T3 fix effect: the baseline wedge rate (~1/3) should go to 0 across 8-10
  boots; a wedge persisting WITH telemetry = the fix is wrong and the
  telemetry names the real mode.

## Procedure per boot (unchanged)
- One row per boot in work/boots.md; wedge -> ring pull BEFORE the next
  boot (dd skip=794623 count=8193); battery gate 25%; pralog=1
  praloglba=794623 always on (the cmdline gate enforces it).

## Outcomes logged against these predictions (2026-11-17 evening)

- P2 PARTIALLY REFUTED: boot #4's clock read 4:07 after a shorter boot.
  A frozen gettimeofday predicts a constant 4:08 every boot regardless of
  duration — refuted. The value = epoch + uptime at render time; within a
  boot the label never advances (boot #1: 4:08 at ~10 and ~15 min). H2's
  NEVER-REDRAWN branch now leads (kernel wall clock substantively fine,
  epoch-seeded, no RTC); the 0176 clock_get_calendar_microtime sampler line
  remains the in-ring confirmation per the standing rule.
- P5: ring38 (boot #4, healthy) byte-identical to ring35 — 3 of 4 healthy
  boots wrote ZERO bytes to the disk ring (header seq frozen at 9). Covered
  by the all-EBUSY / self-erasing-evidence model or a never-started
  flusher; the 0176 strat-flush-at-unlock + header counters are the
  discriminator.
- P1: boots #3-#4 healthy — series 4/4 (+ the pre-series milestone boot).
  The ~1/3 wedge estimate weakens but is NOT refuted ((2/3)^4 ~= 20%).

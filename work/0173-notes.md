# 0173-notes.md — landing the stuck-thread kernel-state reporter (task B)

## What landed (commit bb95144, CI run 43912077062)

- `xnu/patches/0173-pra-stuck-thread-reporter.patch` — extends every
  `SMP <proc> tN ...` sampler line with, per thread:
  `th=0x.. st=0x.. we=0x.. wq=0x.. cont=0x.. kbt 0x.. 0x.. ...`
  - th = thread pointer; st = thread->state; we = thread->wait_event
    (event64_t value; 0 = NO_EVENT64 = a mach_msg2 port receive);
    wq = thread->waitq.wq_q (for a port receive = the port's embedded
    ip_waitq, so port = wq - offsetof(ipc_port, ip_waitq), offline);
    cont = thread->continuation (names the resume point of stackless
    continuation blocks); kbt = kernel fp chain from
    thread_get_kernel_state()->machine.ss (the machine_trace_thread64
    source, osfmk/kdp/ml/arm/kdp_machdep.c:364), bounded to the thread's
    own kernel stack, 8-aligned, downward, <=10 frames, printed only when
    thread->kernel_stack != 0 (continuation blocks free the stack:
    mach_msg.c:932 -> ipc_mqueue.c:890 -> sched_prim.c:3424 ->
    pcb.c:441 kernel_stack = 0).
  - Buffer 400 -> 640 with explicit clamps (0055 had already raised the
    old 220 to 400 for 16 user frames).
- The planned hunk (a) — the vm_user.c mach_vm_deallocate probe + pra_sdhci
  flusher print — was DROPPED: census29 measured 0 of 537 samples at trap
  -12 (the probe's premise was the refuted off-by-one reading).
- CI marker assert added next to the 0172 ones: `grep -F 'cont=0x%llx kbt'`
  (.github/workflows/xnu.yml) — the 0164 anti-silent-skip guard.

## How it was built and verified

- Local git 2.56 false-skips hunks with rc=0 (79 cascaded failures on a
  pristine tree; work/../../tmp evidence in the session). The patch was
  therefore generated deterministically by work/gen0173.py, which replays
  the exception.c hunk lineage (0043, 0051, 0053, 0054, 0055, 0066, 0111 —
  grep-verified as the only patches touching that file) from the pristine
  tarball, inserts the hunk, and emits the diff.
- Verified three ways against the fully-replayed post-0055+0066+0111 state:
  `git apply --check` (no skips), GNU `patch -p1 --fuzz=0 --dry-run`, real
  `git apply` + byte-compare vs the expected final file.
- Hostile-review round (per the refutation rule) found two real bugs that
  were fixed before landing:
  1. BUILD BREAK: adding `#include <kern/thread_kernel_state.h>` would
     redefine `struct thread_kernel_state` — that header's guard macro is
     never `#define`d anywhere (osfmk/kern/thread_kernel_state.h:29 has the
     #ifndef, no #define), and arm/thread.h:84 already includes it under
     MACH_KERNEL_PRIVATE. Fixed by relying on the transitive include.
  2. GUARANTEED PANIC: the first draft dereferenced
     thread_get_kernel_state(thread) BEFORE checking kernel_stack != 0 —
     mach_msg2 receives block at a continuation with the stack detached, so
     the first sampled mach_msg2-parked thread would have faulted at a
     low unmapped VA. Fixed by computing ksb first and gating all reads.
  Residual accepted risk (documented): microsecond TOCTOU if a sampled
  thread detaches its stack exactly during the read and the freed stack
  misses the per-cpu cache (stack.c:229-240, 342). Parked threads do not
  transition; the sampler runs every 120 s.

## What to look for in ring30 (interpretation guide)

- `st=0x<state>`: TH_WAIT = 0x2 (osfmk/kern/thread.h); TH_RUN = 0x4;
  TH_WAIT + others for parked threads.
- `we=0x0` + `cont=0x<ipc_mqueue_receive_continue>` = mach_msg2 port
  receive, stackless — the port is NOT in the line; get it from wq.
- `wq=0x..` != 0: port = wq - offsetof(struct ipc_port, ip_waitq);
  offsetof computed offline from the CI kernel + headers (ipc_port.h:150).
  If wq points into the thread itself (near th=) it is a plain waitq wait
  (GCD/tsleep), not a port.
- `kbt 0x..`: kernel VAs; symbolicate against the CI kernel Mach-O
  (kernel.development.pra) — slide 0 in past boots (verify from the ring's
  printed kernel addresses before trusting).
- The mach_vm_deallocate probe is gone: `PRA VM:` lines will NOT appear.

## Failure modes (from the handoff §6.3 + this patch)

- No `th=0x` lines at all -> the sampler never reached the new code: check
  for `SMP --- sample` lines and the periodic `PRA LOG:`/stats ticks; then
  check the CI log for a `Skipping patch 0173` line (the marker assert
  makes this a build failure, so a green CI rules it out).
- `kbt` empty but th/st/we/wq present: the threads park at continuations —
  expected for mach_msg2 receives; use wq/cont.

## RESULTS (ring30, same-day boot — task C)

The tool worked as designed on first hardware contact: 41 sample records,
100 `th=0x` lines, every field present and decodable (full analysis in
work/ring30-summary.md). Verified behaviors:
- `we=0x0` + `cont=_ipc_mqueue_receive_continue` correctly identifies a
  mach_msg2 port receive (13 permanently-parked threads found this way).
- `cont=_workq_unpark_continue` identifies GCD parks; a thread with a
  mach_msg2 user pc but a workq cont is a CONTINUE_NULL block preserving
  the old continuation (sync-IPC turnstile waits) — do not misread it as
  "blocked in workq".
- `kbt` was absent for every parked thread (all continuation blocks, stack
  freed) — `cont` carried the diagnosis instead. kbt will only pay off for
  stack-kept blocks (msleep-style) or running threads.
- st=0x1 = TH_WAIT (osfmk/kern/thread.h:413 — TH_WAIT is 0x01 in xnu-8796,
  NOT 0x2); st=0x9 = TH_WAIT|TH_UNINT (uninterruptible) — one SpringBoard
  main-thread sample parked uninterruptibly inside mkdirat (BSD 475).
- Caveats learned: the 0166 flusher drops 512-byte chunks under churn load,
  GLUING records ("thSMP Setup t1…") — always split on "SMP " boundaries
  and never trust a per-line parse for field attribution; the ring holds
  MULTIPLE boots' fragments (loader watchdog resets) — classify per line by
  slide + Setup pid, not per sample block.
- Full analysis: work/ring30-summary.md.

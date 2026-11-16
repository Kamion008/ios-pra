# ring34-notes.md — the wedge NAMED: pra_emmc_lock

Black-screen boot (0175 + tweaked root, same image as the milestone boot —
the outcome is stochastic per boot). Render pipeline reached swap 15
(alternating surfaces — re-renders, possibly clock flips), then black; user
saw logo -> black throughout.

0175's blr= + we= fields resolved the blocker:
- launchd (sync thread) and backboardd both UNINT (st=0x9) on
  we=0xfffffff00844dc08 = _pra_emmc_lock+0x8 (kernsym) — THE PRA eMMC
  DRIVER'S OWN MUTEX (the same address as ring32's wedged pair — the lock
  is at a fixed kernel address across boots).
- blr values decoded: _workq_park_and_unlock (benign GCD parks, 128
  records), __sleep (benign), _ipc_mqueue_receive (expected),
  _thread_handoff_internal (yields), and _lck_mtx_lock_contended for the
  UNINT victims.
- CONTRADICTION that defines the bug: the ring flusher kept acquiring
  pra_emmc_lock every tick (stats print throughout, ring written) — the
  lock cycles free, yet the FS-side waiters sleep forever. That is a LOST
  WAKEUP or HOLD-ACROSS-SLEEP in the driver's lock discipline (the 0166-
  0170 flusher changes are the suspects), NOT a stuck holder.
- "A5XELTE FB: display-off request ignored (keep_on)" x2 — the idle
  display-off IS ignored for the panel; no unguarded off path exists in
  SweetFramebuffer.cpp, so ring32's black screen had a different cause
  than backlight sleep. Render pipeline reached swap 15 (re-renders).
- Sampler hit its 90-sample cap; IO quiet at the tail (write storm gone:
  cumulative w 1.4 MB vs ring32's 7.6 MB — the tweaks cut it 5x).

Next: audit pra_sdhci.c's pra_emmc_lock discipline (every acquire/release
pair, the flusher's retry sleep while held, interrupt-context paths);
0176 = fix the lost wakeup (or hold-across-sleep) + a rate-limited
"lock held >10 s" telemetry naming the holder stage/lba.

# ring30-summary.md — the stall, kernel-side (task C, 2026-11-16)

Kernel: 0173 (commit bb95144, CI 43912077062, image out/pra-xnu-0173-kbt.img
sha 226ff2db…). Ring pulled same-day; work/ring30.txt (text), research/
pra-artifacts/ring30.bin (raw, uncommitted). 41 sample records, 100 `th=0x`
lines — the 0173 fields worked exactly as designed.

## Ring structure caveat (matters for interpretation)

The 4 MiB ring holds fragments of MULTIPLE boots, not one: Setup pid ↔ cache
slide ↔ sample-counter map 1:1 ([401]/0xb4b4000 ctr 0-11, [409]/0x2e834000
ctr 15-18, [1512]/0x1a368000 ctr 54-68, ring29's [476]/0x9764000 ctr 80-89),
and the same pid appears with different mh (backboardd[56] mh 0x1005a8000 vs
0x100164000) — distinct boot mappings. The loader phase evidently reset the
phone several times before a boot survived (the 5-11 min loader vs the
bootloader watchdog). Chunk cuts also glue records ("thSMP Setup t1…"): split
on "SMP " boundaries when parsing (naive line parsing mis-attributes fields).
Because the stall pattern is IDENTICAL in every fragment, the conclusions
below hold for this boot and, evidently, every recent boot.

## The stall, kernel-side (current-boot fragment, samples 0-11)

- **13 threads permanently blocked in mach_msg2 PORT RECEIVE**:
  cont=_ipc_mqueue_receive_continue (0xfffffff007288950, kernsym-verified;
  ipc_mqueue.c:890), we=0x0=NO_EVENT64=IPC_MQUEUE_RECEIVE (ipc_mqueue.c:1045),
  st=TH_WAIT (0x1 — thread.h:413; my earlier "0x2" was wrong) on 13 DISTINCT
  port waitqs — backboardd th …511c10/672040/679820/657430/67fc10/750820/
  664820/72b820 → wq 0xfffffff359468618/648/918/9a8/9d8/a08/a38/ac8;
  SpringBoard th …716820/79d040/730430/876c10 → 4684f8/468eeX/467978/…;
  Setup[401] th …778040 → 467138. Zero th→wq transitions across 9-12 samples.
- GCD workers parked: cont=_workq_unpark_continue (0xfffffff00772e230) —
  Setup t3/t4 + ~25 others (Setup stable on wq 0xfffffff76eb711f0/71b80);
  several backboardd/SpringBoard threads cycle workq-stub ↔ mach_msg2-stub
  parks with the SAME cont (a CONTINUE_NULL block preserves the old
  continuation — the stale cont marks threads that once parked in workq).
- Two threads in sys_ulock_wait (backboardd …751c10, SpringBoard …817c10).
- **SpringBoard t0 (main, th=…295040) once seen in st=0x9 = TH_WAIT|TH_UNINT
  (uninterruptible) with upcb pc on the mkdirat stub (BSD 475, decoded:
  MOVZ x16,#475;SVC;B.cond)** — the main thread blocked UNINTERRUPTIBLY
  inside a filesystem mkdir; its line survives only once (chunk cuts), so its
  later history is UNKNOWN — either still in mkdirat or among the receive
  parks. An uninterruptible VFS block is NOT covered by the refuted-theory
  list and is a strong secondary lead (the eMMC write path: the flusher
  logged 14x "write failed 16" = EBUSY).
- kbt is absent for all parked threads — expected: mach_msg2 receives and
  workq parks are continuation blocks (stack freed, kernel_stack=0), so `cont`
  did the naming, exactly as designed in 0173.

## The IPC story

69 probe records (PRA MSG[1..69], lines 1590-1679): Setup-centric bring-up —
launchd look-ups (id=0x40000xxx), notifyd/logd/cfprefsd, a working
Setup↔backboardd render exchange (id=0x111xx, msgs 55-68), SpringBoard's
single send = a reply to Setup (msg 45). **The last recorded IPC ever:
PRA MSG[69]: Setup -> runningboardd id=0x10000000 bits=0x110011 — no reply,
then total IPC silence.** Only churn afterwards (12308 `exec xpcproxy`; the
fairplayd/bluetoothd/nanotimekitcompaniond retry counts 617/615/607 are the
same as ring29), SWEET AKS ioctls, eMMC stats. No panic, no 0x8badf00d in
this boot. driverkitd[66] was SIGKILLed early (CRASH lines 601-604, sig 9,
reason ns 1 code 0x7) — secondary, cause unknown.

## Diagnosis (post-refutation-round)

All GUI-stack threads park waiting for messages that nobody sends; the kernel
is healthy (sampler + flusher keep running); the peers that should send —
runningboardd/launchd/notifyd — are OUTSIDE the sampled set. Refutation
round (independent analyst, raw evidence only) agreed on the wait anatomy and
offered: (a) kernel IPC-delivery bug (weakened: early round-trips worked),
(b) circular wait including unsampled peers, (c) missing-waker deadlock after
Setup's final handoff (top hypothesis). Cheapest discriminator: **add
runningboardd,launchd,notifyd to `sweetsample` — a CMDLINE-ONLY change on the
SAME kernel** — receive-parked ⇒ circular deadlock; exited/spinning ⇒ missing
sender. Second cheapest: 0174 prints, in the sampler, the port's receiver
task name kernel-side (the 0160-probe technique: ip_mq_lock + ip_in_a_space +
task_get_proc_raw — the 0153 panic lesson).

## Retracted during analysis

- "Kernel clock ~4x fast" (69 samples / 31 wall-min): died with the
  multi-boot reading — each fragment's counter is its own boot's. No positive
  evidence of a timebase bug (launchd epoch stamps advance consistently).
- "4 permanent parks": the line-level parse found 13 (my >=5-sightings
  filter + glued records undercounted).

## Next session's exact steps

1. Repackage the SAME 0173 kernel with
   `sweetsample=SpringBoard,backboardd,Setup,runningboardd,launchd,notifyd`
   (the sampler name buffer is 128 B — fits), flash, pull ring31: the three
   new processes' parks answer missing-waker vs circular-wait.
2. If inconclusive: land 0174 = sampler prints the receive port's owner
   (receiver task name) for parked threads; one boot names all 13 peers.
3. Chase the SpringBoard t0 mkdirat TH_UNINT lead: add a rate-limited print
   in the sweet_hfs/sweet_ufs mkdir/create path when a vnode lock is held
   >10 s (0173's flusher-print pattern), or decode more of t0's glued
   records first (free — split on "SMP " boundaries in ring30.txt).
4. Kernel-clock check if ever relevant: compare [+Ns] milestones against
   wall time (today's data was too fragmented to settle it).

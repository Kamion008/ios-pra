NEXT SESSION PROMPT - PRA Touch/RAM/8-core, after T24 early panic (2026-11-23e)

You are continuing the PRA bring-up. Read HANDOFF_2026-11-23e.md first (self-contained,
supersedes 11-23d), then AGENTS.md for mechanics. The phone currently sits panicked in XNU
(T24 image fb96faf3, flashed 19:38:07 UTC, readback verified); return it to TWRP before
pulling rings.

STATE RECAP (VERIFIED):
- CI run 45244377368 (0203 patch 8c735fa) = SUCCESS. Full-stack verified: zero skips,
  cmp rc=0 vs derived post files, already-applied discrimination rc=1 both tools.
  Kernel sha b0d0b4783728698b... matches CI SHA256SUMS.
- T24 image fb96faf38b4a47c7... (6041600 B) = 0203 honesty + RAM 1 GiB→1.375 GiB
  (mem_size 0x58000000, end 0xe0000000), keys on (prapowerkey=900 prakeyevery=30),
  cpus=4, NO a5fb_keep_on=1, all 11 critical args. Panicked ~2 s after power-on,
  BEFORE pralog starts:
    panic(cpu 0 caller 0xffffff007fab5ee4): kmem_range_init:
    vm_map_locate_space failing for claim compressor @ vm_kern.c:3645
- RAM-only variant packaged: out/pra-xnu-0202-1375mb.img (sha 0ba0c97b..., 6039552 B,
  WITH keep_on, keys on, cpus=4, mem_size verified 1408 MiB). NOT flashed.
- Ring67 pulled (work/ring67.raw + work/ring67-full.txt): differs from ring66 only in
  the 98-byte panic-flush tail — boot died before +30 s, no pralog content.
- Photo of panic screen: research/boot-photos/t24-panic-vm_map-20261123-194127.jpg.
- Ring66 (T23) falsified 0202's host-state lever (ZERO host-state pushes despite
  advertisement — claim-0202 K5 hit).
- Battery 100%.

NEXT SESSION, IN ORDER:

1. (no boot) Verify CI run 45244377368 conclusion = SUCCESS (gh run view), and that
   out/pra-xnu-0202-1375mb.img sha = 0ba0c97b... (6039552 B).

2. ISOLATE THE T24 PANIC — flash out/pra-xnu-0202-1375mb.img (RAM-only, keep_on,
   keys on, cpus=4) via tools/pra_flash_skip.sh (readback-verified), battery >= 25%:
   PRA_SERIAL=57U7N17912003349 bash tools/pra_flash_skip.sh out/pra-xnu-0202-1375mb.img
   - If it BOOTS (reaches lock screen): RAM change alone is fine; the T24 panic came
     from the combination (unlikely — honesty is VM-free). Re-verify by re-flashing
     T24 image and watching for the same early panic; then debug vm_kern.c claim
     placement anyway.
   - If it PANICS the same way (vm_map_locate_space failing for claim compressor
     @ vm_kern.c:3645): the 1.375 GiB RAM change breaks early VM claim placement.
     Fix vm_kern.c:3600-3690 (kmem_range_init: claims are shuffled then placed
     contiguously `start = end`; the compressor claim can't find space under its
     restrictions — likely kernel_map max offset / restriction ordering introduced
     by the larger phys window). Fix in vm_kern.c / boot_args handoff.
   - NEVER flash cpus=8 with this image until the RAM panic is resolved.

3. ONLY IF isolation passes: KEITLESS BOOT TEST (the deliverable). Same 0203 image,
   cmdline WITHOUT prapowerkey/prakeyevery AND without a5fb_keep_on=1. Touch must
   work from boot with NO synthetic key. Record in boots.md, claim-XXXX.md, and a new
   dated handoff.

BOOT ARGS - MANDATORY UNTIL THE RAM PANIC IS RESOLVED
Any touch experiment: pratouch=1 pratouchreset=1 pratouchdbg=1 pratouchselftest=1
prapowerkey=900 prakeyevery=30 sweetsample=SpringBoard,backboardd plus pralog=1
praloglba=794623 and the 11 critical args. NEVER boot without pralog=1 praloglba=794623.
cpus=8 requires PRA_ALLOW_ANY_CMDLINE=1 + explicit approval and is expected to panic
(diagnostic only). The T21c base cmdline is work/0198/cmdline.txt (517 B) +
prakeyevery=30; T24 additionally removed a5fb_keep_on=1 (517 B).

HARDWARE TRACKS (designed, awaiting CI slots after 0203 clears the queue):
- 8-core: work/hw-8core-design.md. Patch 0204 (commit 9d6b497) instruments
  __lck_ticket_owned_panic (lock_ticket.c:143) to print owner+re-acquirer ctids;
  three-way verified, zero skips on 195-patch stack; CI not yet run (cancelled run
  45246061084 behind the slow queue). cpus=8 boot = EXPECTED panic on pset0.sched_lock;
  console capture (wdt=-1 keeps it on screen), then 0205 fix. Needs explicit user
  approval for the cpus=8 flash.
- RAM 1.375 GiB: work/hw-3gb-design.md (this is the active blocker above).
- GPU: work/hw-gpu-status.md. G3D is LPM3-IPC power-managed
  (hi3xxx_to_lpm3_enable_step <0x00030004>); blocker is establishing G3D power/clock
  before any MMIO (ring26 precedent: sync external abort panic). Not flashable in
  parallel with touch.

DELIVERABLE: touch works from boot with NO synthetic key; record in boots.md,
claim-XXXX.md, and a new dated handoff. Until then the answer stands as evidence:
a wake event DOES re-enable the digitizer; SpringBoard's asserted LockButton
sensor-mode (score 4108, multitouchHostStateKeys incl. WakeOnTapEnabled) is what
makes backboardd believe the panel is awake.

RULES (AGENTS.md authoritative): kernel-side only; flash only p27 via
pra_flash_skip.sh readback-verified; never p30/p32/bootloaders; serials via
PRA_SERIAL only; durable numbers via python3/bc quoted and labelled VERIFIED/
INFERRED/UNKNOWN; three-way patch verify; marker assert per patch; commit subject
`pra: ...`; no AI footer; push master, trigger CI with RUNNER=macos-15 (push-triggered
run targets A5XELTE — cancel it); battery >= 25%; explicit user approval (exact
command shown first) before any flash; do not commit work/ci*/, work/pkt-*/,
shim/pra/out* or raw rings.

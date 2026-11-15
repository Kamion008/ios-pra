# Session record — 2026-11-14: the zone_require panic is SOLVED (it was our own probe)

Repo: `/home/kamion008/Ai/ios/ios-pra`, HEAD `bd0e668`. Phone PRA-LX1 `57U7N17912003349`
rebooted into XNU at ~18:14 with 0160 (`pra-xnu-0160-probe-fix.img`, sha256
`f74d10b5761c…2bfb396`), full gated cmdline.

## What the 0159 boot delivered (ring16, `research/pra-artifacts/ring16.txt`)

- 9 `PRA BT:` frames captured in the ring AND printable on screen (0159's printf fix);
  panic flush printed `lock stuck, stealing`, stole the lock, wrote the ring. No doubled
  lines (0159's `_cnputs` fix).
- Slide this boot ≈ 0 (caller 0xfffffff007a98a6c = link layout directly). Frames
  symbolized (llvm-nm on the CI kernel, link base 0xfffffff007004000):
  ```
  frame 0  0xfffffff007a98ad0  ___zone_site_register+0x0   (= bl zone_require_panic, noreturn tail of zone_id_require_panic)
  frame 1  0xfffffff00731cdd4  _zone_id_require+0x74
  frame 2  0xfffffff00732e990  _get_bsdtask_info+0x20      (= return after bl _proc_require)
  frame 3  0xfffffff00727ecd0  _ipc_kmsg_send+0x140        (= return after bl _get_bsdtask_info — inlined pra_msg_probe)
  frame 4  0xfffffff00729532c  _mach_msg_trap_send+0x17c
  frame 5  0xfffffff0072957b0  _mach_msg2_trap+0x210
  frame 6  0xfffffff007416d88  _mach_syscall+0x198
  frame 7  0xfffffff007426268  _sleh_synchronous+0x688
  frame 8  0xfffffff0074255a4  _fleh_synchronous+0x28
  ```

## Root cause

0153's `pra_msg_probe` (Setup mach-msg tracer) did:
`space = ip_get_receiver_ptr_noauth(port); if (space != IPC_SPACE_NULL) receiver =
space->is_task;` — but `ip_receiver` is a union with `ip_destination` and is an
ipc_space_t only while `ip_in_a_space(port)`. Mid-churn (exec storm) it read a
destination PORT as a space → garbage `is_task` → garbage `bsd_info`
(`0x1a902fffff880`, 0158b: `0x1b202ffffff080`) → `get_bsdtask_info` →
`proc_require` → `zone_id_require` → **zone_require panic**. It also ran BEFORE
`ip_mq_lock(port)`, racing the union transition. Every zone_require panic since 0156
was this probe, not Apple code.

## 0160 fix (commit `bd0e668`, CI run 43619486927 ✓)

- Probe called under `ip_mq_lock(port)`; receiver extracted only when
  `ip_in_a_space(port)`.
- `pra_task_comm` uses `task_get_proc_raw` (raw, cannot panic; NULL = "kernel").
- Patch recipe that worked (learned the hard way — diff against a COMMITTED base;
  an uncommitted 0159 base turned 0160 into a 0158+0159+0160 combo): fresh copy of
  xnu-src → `git apply 0158` → `git apply 0159` → `git add -A && git commit` → make
  edits → `git diff` = clean 0160.

## Cmdline hardening (commit `186201b`)

`tools/pra_package.sh` now DEFAULTS to the full proven cmdline (0153..0158b string,
incl. `emmcmulti=0`, `pralog=1 praloglba=794623`, `wdt=-1`, `cpus=4`) and self-verifies
12 critical args in the packaged image; `tools/pra_flash_skip.sh` refuses to flash an
image missing them (bypass `PRA_ALLOW_ANY_CMDLINE=1`). The block is in AGENTS.md,
PRA-LX1_PROGRESS.md, DEEPSEEK_HANDOFF.md. Note: xnu-src carries its own .git (HEAD at
the 0133 era, working tree = patch stack through 0157); its reflog stays idle during
sessions — do not treat it as a race indicator.

## Next steps

1. 0160 boot outcome: check the screen (user photographs anything interesting) and pull
   ring17 (`OUT=/tmp/opencode/pra/ring17.bin TXT=$PWD/research/pra-artifacts/ring17.txt
   PRA_SERIAL=57U7N17912003349 sh tools/pra_readlog.sh`). Boot should now run PAST the
   zone_require panic — whatever fails next is the real next bug.
2. `addr 0x1a902fffff880` / `0x1b202ffffff080` mystery: closed as probe artifacts
   (union misread), no kernel bug implied.
3. Keep the flash gate intact; never package without the critical args.

## 2026-11-15 addendum: the userspace crash-loop is a KNOWN issue, not a 0160 regression

- **Symbolized (offline, from research/ipsw-x 20H392 cache + .symbols):**
  pc 0x1f6748894 - slide 0x24b48000 = 0x1d1c00894 = **`__xpc_api_misuse+0x4c` in
  /usr/lib/system/libxpc.dylib** (deliberate XPC API-misuse trap), reached via
  libdispatch (`__dispatch_once_callout`) and **libATCommandStudioDynamic.dylib**
  (baseband AT-command framework), from the daemons' own init. Chain:
  locationd/WirelessRadioManagerd init -> dispatch_once -> ATCommandStudio ->
  libxpc misuse trap. Same for PosterBoard (ring8).
- **Donor devices (S8/SWEET, same 20H392 userland): NEVER hit this crash** — their
  boots died at the display wall (backboardd window-server exception, SpringBoard
  FBSDisplayMonitor) before this depth. Their locationd failed earlier and
  differently (sig 11, CFRunLoopAddSource+132 NULL source, 0045n era), and
  WirelessRadioManagerd ran without recorded crashes. Their last identified wall:
  launchd sandbox denials (mach lookup error 159, tccd OS_REASON_SANDBOX "profile
  not found") — the reason 0050-sweet-sandbox-policy exists in our stack.
- **Our phone 2-3 days ago (ring5-12, all 0151 boots, 13 nov):** the crash-loop was
  ALREADY THERE whenever the radio daemons were allowed to run. ring8 (3244 execs,
  1 h boot) had NO locationd/WirelessRadioManagerd crashes because `praexecskip`
  (0147) skipped them. ring10 (skip list removed): locationd and
  WirelessRadioManagerd died with sig 5 code 0x600000001 at
  0x1e5e4c894 / slide 0x1424c000 = the SAME unslid pc 0x1d1c00894 as ring17.
  launchd printed "Too many corpses being created". Notes concluded: "Keeping
  those jobs disabled is therefore the better default."
- **The hello-screen blocker (identified 13 nov, PRA-LX1-noted.md ring10 section):
  Setup execs once, never requests a scene; its second thread parks in
  xpc_connection_send_message_with_reply_sync() — a sync XPC reply that never
  comes.** The 0153 probe was built to name that peer; the probe bug then caused
  the zone_require panic saga (0156-0159), which 0160 fixed.
- **ring17 probe results (0160, hours of runtime):** 128 distinct triples captured
  (Setup talks to kernel, launchd, notifyd, logd, backboardd, SpringBoard,
  cfprefsd, runningboardd, MobileGestaltHelper, mobileactivation,
  containermanagerd, profiled, CommCenter, configd, distnoted, accountsd; many
  `id=0x77303074 'w00t'` bootstrap requests answered with id=0x20000000), then the
  128-entry table FILLED and the sampled overflow shows the dominant remaining
  traffic: **kernel_task -> Setup id=0x0 bits=0x11, thousands of times** —
  suspicious enough to need identification (own diagnostic patch? kernel service?).
  The probe needs tuning: bigger table (512+), filter the kernel_task->Setup
  id=0x0 noise, and ideally track UNANSWERED sync requests.
- Kernel-era timeline of the ring pulls: ring2-5 = late-night 12-13 nov session
  pulls; ring7/8 = 0151 one-hour boots (watchdog key); ring9/10 = single-variable
  skip-list tests; ring11/12 = same log pulled twice (frozen boot); ring13/14 =
  0153/0156-era boots that died at dasd (probe panic, flush skipped); ring15 =
  0158b (panic text never flushed, photo captured it); ring16 = 0159 (BT captured);
  ring17 = 0160 (this boot).

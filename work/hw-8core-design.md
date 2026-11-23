# hw-8core-design.md — running ALL 8 cores on PRA-LX1 (hi6250 / Kirin 655)

Scoping note, 2026-11-23. Read with AGENTS.md + HANDOFF_2026-11-23d.md.
Source: explore sub-agent (read-only), persisted by the parent session.
Evidence labels: VERIFIED (file:line / quoted command), INFERRED, UNKNOWN.
All arithmetic computed with python3 and quoted. Compiled-state source read
from /tmp/opencode/ci-tree-0201/src/xnu (post-0201 CI tree).

## 0. Bottom line (the surprise)

The port is **already 8-core capable in source, ADT and board config**. Selecting
8 cores is a **cmdline-only change** (`cpus=4` → `cpus=8`): no kernel rebuild, no
ADT edit, no shim edit. **But `cpus=8` was already booted on PRA and it PANICS** —
a recursive ticket-lock acquire on `pset0.sched_lock` while bringing up the second
physical cluster. The identical panic was seen on the Exynos donor. PSCI itself
works (`CPU_ON rc=0`).

So this item is **not** "enable 8 cores" (that is done); it is **"fix the
cluster-1 scheduler/processor-registration panic"**. `cpus=4` is the proven value
because it selects cluster 0 only and never touches the broken path.

- VERIFIED: `cpus=4` = logical 0..3 = MPIDR 0x0..0x3 = cluster 0 (the 1.7 GHz
  cluster). `cpus=8` adds logical 4..7 = MPIDR 0x100..0x103 = cluster 1 (2.1 GHz).
  python3: `cpus=4 -> ['0x0','0x1','0x2','0x3']`; `cpus=8 -> ['0x0','0x1','0x2','0x3','0x100','0x101','0x102','0x103']`.
  (PRA-LX1-noted.md:704-707 mislabels cluster 0 as "2.1 GHz"; mkadt_pra.py:33-34
  and the stock OPP tables show cluster 0 = 1.7 GHz, cluster 1 = 2.1 GHz. The
  MPIDR mapping, not the GHz label, is what matters.)
- VERIFIED: the prior PRA `cpus=8` panic (PRA-LX1-noted.md:769-795), reproduced
  from the donor (A5XELTE_PROGRESS.md:94).

## 1. How secondary cores are brought up today

### 1a. The shim does NOT release secondaries
- /home/kamion008/Ai/ios/ios-pra/shim/pra/start.S:21-46 — `entry` runs on the
  boot CPU only (Huawei bootloader enters with x0 = live DTB, MMU off). It clears
  .bss and calls `pra_main`; on return it parks in `wfe` (start.S:45-46). There is
  **no spin-table, no PSCI CPU_ON, no secondary release** anywhere in the shim.
- start.S:48-60 — `el2_to_el1` drops the *boot* CPU from EL2 to EL1 if needed
  (HCR_EL2.RW=1, CNTHCTL_EL2=3, eret). It does not touch other cores.
- /home/kamion008/Ai/ios/ios-pra/shim/pra/boot_main.c:129-258 — `pra_main` copies
  payload segments, places ADT + boot_args, fills boot_args, and jumps
  (boot_main.c:256-257 `ic iallu; dsb; isb` then `pra_jump_mmu_off`). Single-core.
- /home/kamion008/Ai/ios/ios-pra/shim/pra/xnu_jump.S:11-21 — turns MMU/D/I off,
  passes boot_args in x0, `br x16` to XNU `_start`.
- /home/kamion008/Ai/ios/ios-pra/shim/pra/probe.c:415-426 — the *diagnostic* shim
  uses PSCI v0.1 **SMC** `SYSTEM_RESET` (x0=0x84000009). Comment probe.c:415:
  "PSCI v0.1 on hi6250 uses the SMC conduit." This proves the SMC conduit works on
  this phone (VERIFIED reset loops, PRA-LX1_PROGRESS.md:322-325). It is not CPU_ON.

Conclusion (VERIFIED): **XNU brings up secondaries, not the shim.** The shim
delivers one core; the other seven are parked in firmware until XNU issues PSCI
CPU_ON.

### 1b. XNU side: PSCI CPU_ON via the SweetCPU IOCPU driver
- /tmp/opencode/ci-tree-0201/src/xnu/iokit/Kernel/arm/SweetCPU.cpp:40-51 —
  `sweet_psci_cpu_on(target, entry, context)` issues **SMC64 x0=0xC4000003**
  (PSCI CPU_ON), SMCCC 1.0 clobber list. This is the function ID the stock DT
  publishes (see §3).
- SweetCPU.cpp:159-213 — `startAll` (a kernel thread spawned by the boot CPU's
  nub, SweetCPU.cpp:147-154): reads `cpus` boot-arg (:164), waits for all
  `num_cpus` nubs to register (:170-180, 10 s deadline), asserts boot MPIDR ==
  A5_BOOT_MPIDR (:182), then for each logical CPU calls `processor_start`
  (:187) and waits for `initialized` + self-SGI delivered (:192-201, 10 s
  deadline), logging `cpu=%u mpidr=0x%x came alive; SGI1 OK` (:202). Finally
  `ml_cpu_init_completed()` + `cpusRunning()` + `ml_set_max_cpus` (:206-209).
- SweetCPU.cpp:287-356 — `startCPU`: `entry = ml_static_vtop(&sweet_secondary_entry)`
  (:296), logs `CPU_ON target=... entry_pa=... context=...` (:297), DSB SY,
  `sweet_psci_cpu_on(cpu->phys_id, entry, getCPUNumber())` (:349), panics if
  rc != 0 (:352-353). (The DREAMLTE low-trampoline + PMU power-up block
  :299-347 is **compiled out on PRA** — PRA.h does not define DREAMLTE.)
- SweetCPU.cpp:223-254 — `initCPU` runs on the secondary: broadcasts CPU_BOOTED,
  queues self-SGI (`signalCPU(this)`), and on A5XELTE briefly unmasks IRQs to
  service the queued self-SGI before returning (:237-249, patch 0113), then
  publishes `initialized=1`.
- /tmp/opencode/ci-tree-0201/src/xnu/osfmk/arm64/start.s:282-332 —
  `sweet_secondary_entry` (physical PSCI entry, MMU/caches off): masks DAIF,
  checks CurrentEL; EL2 path sets HCR_EL2/VTTBR/CNTHCTL=3/**CNTVOFF_EL2=0**
  (:301-308), skips ICC_SRE on A5XELTE/GICv2 (:309-315), sets SCTLR RES1
  0x30d00800, erets to EL1; EL1 path goes straight to `LowResetVectorBase`
  (:328-331).
- start.s:126-196 — `reset_vector` reads MPIDR_EL1, masks `& 0xFFFF` (Aff1:Aff0,
  :146-150, SWEET/A5XELTE path), scans `CpuDataEntries[0..MAX_CPUS)` for a matching
  `CPU_PHYS_ID` (:151-163), then calls the reset handler (`start_cpu` →
  `arm_init_cpu`). This is MPIDR-based, cluster-agnostic.
- /tmp/opencode/ci-tree-0201/src/xnu/osfmk/arm64/cpu.c — `cpu_start` cleans
  CpuDataEntries/CpuData/ResetHandlerData/BootArgs/sysreg_restore/cpu_ttep/
  bootstrap_pagetables to PoC before CPU_ON (patch 0065, the `#if defined(SWEET)`
  CleanPoC block; PRA-LX1-noted.md:695-698). Needed because the secondary enters
  with caches off.

### 1c. Where `cpus=N` is parsed and what it bounds
- /tmp/opencode/ci-tree-0201/src/xnu/osfmk/arm64/machine_routines.c:946-1151 —
  `ml_parse_cpu_topology`. :957 `PE_parse_boot_argn("cpus", &cpu_boot_arg, ...)`.
  :960-968 SWEET/A5XELTE/PRA clamp: absent/0 → 1; `> SWEET_SMP_MAX_CPUS` → 8.
  :1010-1015 the bound: it ingests ADT `/cpus` children **in DT order** until
  `num_cpus >= cpu_boot_arg`, reserving a slot for the boot CPU. So `cpus=N`
  selects a **prefix of the ADT cpu nodes** (logical 0..N-1). :1019
  `cpu->cpu_id = num_cpus++`; :1026 `phys_id = ml_readprop(child,"reg")`.
  :1053-1062 cluster id from `MPIDR_CLUSTER_ID(phys_id)` (A5XELTE path);
  :1113-1126 builds `cluster_offsets` (assert total <= MAX_CPUS).
- /tmp/opencode/ci-tree-0201/src/xnu/iokit/Kernel/IOPlatformExpert.cpp:1622-1684 —
  `createNubs` makes an IOCPU nub per ADT `device_type=="cpu"` node, sets
  `logical-cpu-id = ml_get_cpu_number(phys_id)` (:1655-1672). A CPU ignored by
  `cpus=N` gets logical_id < 0 and is skipped (:1667-1670) — this is why cpus=4
  leaves cpu4..7 nubs unmatched.
- ml_get_cpu_number (machine_routines.c:1210-1222) is a **linear scan by phys_id**
  — correct for any cluster count (no cluster_offsets indexing hazard here).

### 1d. GICv2 interrupt / IPI path (no redistributor)
- /tmp/opencode/ci-tree-0201/src/xnu/pexpert/arm/pe_fiq.c:226-331 — A5XELTE GICv2
  branch (`HAS_GIC_V3==0`). `pe_init_fiq` maps GICD/GICC from ADT once on the boot
  CPU (:292-305), then **per core** reads banked `ITARGETSR0` (GICD+0x800) to learn
  this core's CPU-interface bit (:309-315), enables vtimer INTID + SGI1
  (:316-322), sets GICC_PMR/BPR/CTLR and GICD_CTLR (:323-328).
- pe_fiq.c:256-272 — self-IPI = GICD_SGIR (0xf00) `(2<<24)|1` (target-list, SGI1);
  cross-CPU IPI = `a5xelte_send_ipi(logical)` using the recorded target mask
  `(mask<<16)|1`. Patch 0114 masks IAR with 0x3ff so SGI INTID is decoded correctly.
- The GICv3 redistributor-wake code (pe_fiq.c:16-224) is **compiled out** on PRA
  (`HAS_GIC_V3==0`, PRA.h:36). There is **no GICR** to wake on hi6250 — GICv2 has a
  banked CPU interface, not redistributors.

## 2. What the ADT publishes about CPUs

- /home/kamion008/Ai/ios/ios-pra/tools/mkadt_pra.py:109-154 — cpu0 comes from the
  donor builder (tools/mkadt.py:126-149, qemu=True → 1 node, reg 0, device_type
  cpu, cpu-id 0, state running); mkadt_pra overrides cpu0 compatible/reg/clocks
  (:111-126) and **appends cpu1..cpu7** (:133-154) with
  `cluster,core = divmod(logical,4); mpidr=(cluster<<8)|core`.
- VERIFIED by in-memory inspection of `mkadt_pra.build()` (python3, little-endian
  ADT decode; no file written):
  ```
  cpu node count: 8
  cpu0 reg=0x000 state=running clock=1700000000 timebase=1920000 die-cluster-id=0 cluster-core-id=0
  cpu1 reg=0x001 state=stopped clock=1700000000 ... die-cluster-id=0 cluster-core-id=1
  cpu2 reg=0x002 state=stopped clock=1700000000 ... die-cluster-id=0 cluster-core-id=2
  cpu3 reg=0x003 state=stopped clock=1700000000 ... die-cluster-id=0 cluster-core-id=3
  cpu4 reg=0x100 state=stopped clock=2100000000 ... die-cluster-id=1 cluster-core-id=0
  cpu5 reg=0x101 state=stopped clock=2100000000 ... die-cluster-id=1 cluster-core-id=1
  cpu6 reg=0x102 state=stopped clock=2100000000 ... die-cluster-id=1 cluster-core-id=2
  cpu7 reg=0x103 state=stopped clock=2100000000 ... die-cluster-id=1 cluster-core-id=3
  serialized ADT bytes: 12872
  gic reg cells (LE u64): ['0x82b1000','0x1000','0x82b2000','0x1000']
  gic virtual-timer-intid: 27
  ```
- **reg = MPIDR** (0x000..0x003, 0x100..0x103), `state` running/stopped (XNU's
  `ml_is_boot_cpu` keys on "running", machine_routines.c:914-929). All 8 carry
  `device_type=cpu` (so all 8 become IOCPU nubs). timebase-frequency 1920000 on
  every node.
- **No `enable-method` property** — Apple ADT does not use it; XNU drives PSCI
  directly through SweetCPU. (The stock Linux DT uses enable-method="psci"; XNU
  ignores that field.) INFERRED: nothing in the PRA XNU path reads enable-method.
- GIC node (mkadt_pra.py:167-172): compatible "arm,cortex-a15-gic", reg offsets
  0x82B1000/0x1000 (GICD) + 0x82B2000/0x1000 (GICC) from SOC_BASE 0xE0000000.
  python3: `0xE0000000+0x82B1000 = 0xe82b1000`, `+0x82B2000 = 0xe82b2000`.
- The ADT is already correct for 8 cores; **no ADT change is needed for cpus=8.**

## 3. What the STOCK PRA device tree / kernel say about the 8 cores

Vendor source tree (partial: arch/arm64 has boot/dts only, no kernel/):
/home/kamion008/Ai/huawei/hi6250-kernel.

- CPU nodes — .../arch/arm64/boot/dts/auto-generate/overlay/hi6250/hisi_6250_cpu.dtsi:8-164:
  `little0..3` cpu@0..3 reg <0x0 0x0..0x3>, compatible "arm,cortex-a53";
  `big0..3` cpu@100..103 reg <0x0 0x100..0x103>, compatible **"arm,cortex-a5x"**
  (vendor label; sched-energy-costs reference A72). **All 8 `enable-method="psci"`**
  (:14,:33,:52,:71,:91,:111,:131,:151). cpu-map (:261-292): cluster0 = little0..3,
  cluster1 = big0..3. OPP tables: cluster0 max 1709000 kHz (:24), cluster1 max
  2112000 kHz (:101,:220) — confirms cluster0=1.7 GHz, cluster1=2.1 GHz.
  Idle-states entry-method "arm,psci" (:233).
- PSCI node — .../auto-generate/config/hi6250/hi6250_udp_default_config.dtsi:58-66:
  ```
  psci { compatible = "arm,psci"; method = "smc";
         cpu_suspend = <0xc4000001>; cpu_off = <0x84000002>;
         cpu_on = <0xc4000003>; system_off = <0x84000008>;
         system_reset = <0x84000009>; };
  ```
  **`cpu_on = 0xc4000003` is exactly XNU's `sweet_psci_cpu_on` function ID**
  (SweetCPU.cpp:43). VERIFIED match. `system_reset=0x84000009` matches probe.c:418.
- GIC — .../overlay/hi6250/hisi_6250_gic.dtsi:4-15: interrupt-controller@e82b0000,
  compatible "arm,cortex-a9-gic" (GICv2), reg GICD 0xe82b1000/0x1000 + GICC
  0xe82b2000/0x1000. (A stray `redistributor-stride` prop is a GICv3 leftover;
  GICv2 has no redistributor.)
- Timer — .../overlay/hi6250/hisi_6250_timer.dtsi:4-12: arm,armv8-timer,
  interrupts PPI 13/14/11/10 (sec-phys/ns-phys/virt/hyp), **clock-frequency
  1920000**. No `use-physical-timer` here (contrast Samsung dreamlte, which sets
  it; A5XELTE.h:45-51).
- Live stock dmesg — /home/kamion008/Ai/ios/ios-pra/live/dmesg.txt:
  :7 Boot CPU [410fd034]; :35-36 "psci: Using PSCI v0.1 Function IDs from DT";
  :41 "enabling workaround for ARM erratum 845719"; :62 "Architected cp15 timer(s)
  running at 1.92MHz (virt)"; :270-290 CPU1..7 "Booted secondary processor
  [410fd034]"; :291-293 "Brought up 8 CPUs / Total of 8 processors activated /
  **All CPU(s) started at EL1**"; :232,:280 cpu_capacity 659 (cpu0-3) vs 1024
  (cpu4-7) = the two clusters.
  python3 MIDR decode: `0x410fd034 partnum=0xd03 revision=4 variant=0` →
  **Cortex-A53 r0p4 on all 8 cores** (the "cortex-a5x"/A72 DT label is cosmetic).
- Stock kernel config — /home/kamion008/Ai/ios/ios-pra/live/config.gz (zcat):
  `CONFIG_SMP=y`, `CONFIG_NR_CPUS=8`, `CONFIG_HOTPLUG_CPU=y`, and errata
  `ARM64_ERRATUM_826319/827319/824069/819472/832075/845719/843419=y`.
- HiSi-specific SMP ops: **none required** — enable-method is standard "psci" and
  the vendor kernel uses the generic PSCI driver (the local tree has no
  arch/arm64/kernel/smp.c to inspect; UNKNOWN whether Huawei patched PSCI, but
  the DT function IDs + the working stock 8-core boot are the evidence that
  matters). No spin-table / hisi boot-wrapper is used.

## 4. What is hardcoded to 4 / one cluster, and the errata / boot risks

### 4a. Nothing in the port is hardcoded to 4 anymore
- /tmp/opencode/ci-tree-0201/src/xnu/pexpert/pexpert/arm64/PRA.h:16
  `SWEET_SMP_MAX_CPUS 8`; :36 `HAS_GIC_V3 0`; :38 `A5XELTE_VTIMER_INTID 27`;
  :58 `A5_BOOT_MPIDR 0`. PRA defines SWEET=1 and A5XELTE=1 (PRA.h:14-15) but
  **not DREAMLTE**, so the non-DREAMLTE MPIDR map applies.
- board_config.h:125-133 (ARM64_BOARD_CONFIG_PRA): `MAX_CPUS 8`,
  `MAX_CPU_CLUSTERS 2`, `MAX_L2_CLINE 6`, `CORE_NCTRS 8`. :155-157 `__ARM_AMP__`
  is undefined only when MAX_CPU_CLUSTERS==1 → PRA keeps AMP (2 clusters).
- SweetCPU.cpp:87-103 (non-DREAMLTE A5XELTE): `expected_mpidr = cpu_id<4 ? cpu_id
  : 0x100+cpu_id-4`. python3 confirms this equals the ADT reg list exactly:
  `[0,1,2,3,256,257,258,259]`.
- cluster_offsets: python3 `c0 size 4 + c1 size 4 = 8 <= MAX_CPUS 8: True`.
- Patch history: 0065 (donor PSCI), 0078 (donor 8), 0112 (A5 2-core), 0113
  (secondary self-SGI service), 0114 (GICv2 IAR 0x3ff mask), 0115 (A5 8-core /
  2-cluster), 0125 (PRA board, MAX_CPUS 8 / 2 clusters), 0129 (A5_BOOT_MPIDR 0 +
  ARMv8.0 commpage LL/SC). All landed.
- **The only thing selecting 4 today is the cmdline literal `cpus=4`**, enforced
  as a critical arg in tools/pra_package.sh:90 and tools/pra_flash_skip.sh:54.
  VERIFIED current boot-args carry cpus=4 (work/ring65-full.txt:194).

### 4b. THE KNOWN BLOCKER — cluster-1 recursive ticket-lock panic (VERIFIED)
PRA-LX1-noted.md:769-778 records the actual PRA `cpus=8` boot:
```
A5XELTE CPU: requested=8 selected=8 (limit=8)
A5XELTE CPU: cpu=0 mpidr=0x0 came alive; SGI1 OK
A5XELTE CPU: cpu=1 CPU_ON target=0x1 entry_pa=0x89425000 context=1
A5XELTE CPU: cpu=1 PSCI CPU_ON rc=0
panic(cpu 0 caller ...lock_ticket.c:143): Ticket lock 0xfffffff007b70880
  is unexpectedly owned by thread 0xfffffff65a54c820
```
- `0xfffffff007b70880` = `pset0 + 0x100` = `pset0.sched_lock` (lck_ticket_t);
  the panic is the recursive-acquire detector in `lck_ticket_contended`
  (PRA-LX1-noted.md:780-782). python3: `pset0+0x100 = 0x100 = 256 bytes`;
  `entry_pa 0x89425000 in RAM window [0x88000000,0xC8000000): True`.
- **Identical on the Exynos donor** (A5XELTE_PROGRESS.md:94): "the eight-core
  trial reached CPU1 but panicked on CPU0 with an unexpectedly owned ticket lock
  while registering the second physical cluster. Selecting cpus=4 ... produced
  ... 4/4 CPUs initialized, SGI1 verified."
- What this proves (VERIFIED): PSCI CPU_ON works on PRA (rc=0), CPU0 self-SGI
  works, the ADT/topology parses 8. **The failure is in the scheduler /
  processor-registration layer when the second cluster comes up — not in PSCI,
  the ADT, the shim, or the cmdline.**
- Code path (VERIFIED anchors, root cause UNKNOWN):
  - startAll → `processor_start` → `processor_startup`
    (/tmp/opencode/ci-tree-0201/src/xnu/osfmk/kern/processor.c:776-949):
    `pset_lock(pset)` at :830, `pset_update_processor_state(...PROCESSOR_START)`
    at :855, `cpu_start` at :915.
  - The secondary's own `processor_up`
    (/tmp/opencode/ci-tree-0201/src/xnu/osfmk/kern/machine.c:161-209):
    `simple_lock(&sched_available_cores_lock)` :187 then `pset_lock(pset)` :188,
    `pset_update_processor_state(...PROCESSOR_RUNNING)` :192.
  - `pset_update_processor_state`
    (/tmp/opencode/ci-tree-0201/src/xnu/osfmk/kern/processor.h:605-637) asserts
    the pset is already locked and does not itself re-lock; it calls
    `sched_update_pset_load_average` (:633). The recursive acquire is therefore
    introduced somewhere in the cluster-specific registration / clutch-scheduler
    rebalance path, not in this inline itself.
- Leading hypotheses (INFERRED, from PRA-LX1-noted.md:792-795): per-cluster
  `ml_processor_register` bookkeeping; `cluster_type`/cluster-id handling; the
  second cluster's `pset_update_processor_state` / clutch node rebalance racing
  the boot CPU's startAll thread that already holds pset0.sched_lock. The donor
  SWEET is single-cluster (MAX_CPU_CLUSTERS 1, board_config.h:105) so this path
  was never exercised there; A5XELTE/PRA (2 clusters) is the first to hit it.

### 4c. Errata / second-cluster boot risks
- **A53 errata: XNU has NONE.** grep of the CI tree for
  errata/826319/827319/824069/819472/845719/835769/1009519 found only unrelated
  i386/ comments — no Cortex-A53 workaround code. Stock Linux enables 7 errata
  (§3). INFERRED low risk for cluster 1 specifically: cluster 0 is the **same
  A53 r0p4** and boots 4 cores fine without workarounds, so cluster 1 should not
  need them either. 845719 (the one stock dmesg names) is an AArch32 erratum;
  XNU is AArch64-only. UNKNOWN: whether 843419 (A53 r0p4 exclusive/atomic) matters
  for the commpage LL/SC path (0096/0129) under 8-core contention — worth watching
  but not the current blocker.
- **Per-core timer (the DREAMLTE warning).** PRA uses the **virtual** timer
  (`A5_USE_PHYS_TIMER` is NOT defined in PRA.h; machine_routines.c:2057/2189/
  2216/2297 take the CNTV_* branch). A5XELTE.h:45-51 records that on Exynos 8895
  the EL1 virtual timer was unusable on secondaries (CNTVOFF skew) and they
  switched to the physical timer (PPI 30). On hi6250, stock Linux runs the
  **virt** timer at 1.92 MHz on all 8 cores (dmesg:62 + kworkers on cpu4-7), so
  CNTVOFF is consistent under Linux PSCI. INFERRED ok on PRA, but **UNKNOWN**
  whether XNU's PSCI entry leaves CNTVOFF_EL2 = 0 on cluster-1 cores:
  `sweet_secondary_entry` zeroes CNTVOFF only on the **EL2** path (start.s:308);
  if firmware returns a secondary at **EL1** with a non-zero CNTVOFF left by the
  bootloader, its CNTVCT would be skewed → scheduler stall on that core. Stock
  dmesg:293 "All CPU(s) started at EL1" suggests EL1 entry is the norm here.
  python3: `1.92 MHz tick = 520.83 ns; 10 s startup deadline = 19200000 ticks`.
- **GICv2 cluster-1 CPU interface.** No redistributor to wake (§1d); the banked
  GICC at 0xE82B2000 is per-core. UNKNOWN: whether cluster-1 GICC access is
  powered/clocked at XNU PSCI entry (firmware should power it with the core).
  The ITARGETSR0 mask discovery (pe_fiq.c:309-315) panics if a core reads mask 0
  or a multi-bit mask — a clean falsifier if cluster-1 GIC is not up.
- **cpus=1 hangs** (VERIFIED, PRA-LX1_PROGRESS.md:26, pra_package.sh:17): the
  single-CPU path never completes SMP boot. Keep N>=4.

## 5. Concrete experiment design

Goal: get `8/8 CPUs initialized, SGI1 verified` and sustained scheduling on
cluster 1, without regressing the proven cpus=4 boot. Order is chosen so each
step is a falsifier for the next.

### Phase 0 — offline (no flash, no device) — DONE in this scoping
- Confirm source/ADT/board are 8-capable (§1-4): VERIFIED.
- Confirm the blocker is the reproduced scheduler panic, not PSCI: VERIFIED
  (PRA-LX1-noted.md:769-795).
- Deliverable: an instrumentation patch (Phase 2) designed against
  processor.c:830/855, machine.c:187-192, processor.h:605, and the clutch
  `pset_made_schedulable` / node-rebalance path. Identify every acquisition of
  pset0.sched_lock reachable from startAll and from a cross-cluster processor_up.

### Phase 1 — cmdline-only flash experiments (NO kernel rebuild)
The kernel already supports 8; only the cmdline changes. Two ways to set it:
- Clean: `CMDLINE='... cpus=N ...' tools/pra_package.sh out/ci-0201/kernel.development.pra`
  (regenerates ADT+payload; pra_package.sh:54/64). The packaged image gate
  (pra_package.sh:89-99) hard-checks the literal `cpus=4`, so a cpus≠4 image
  fails the gate → flash with `PRA_ALLOW_ANY_CMDLINE=1` (pra_flash_skip.sh:69-75).
- Quick (donor method, VERIFIED to have existed): the cpus digit is one byte in
  the **raw** image at file offset **0x80860** (PRA-LX1-noted.md:711-714).
  python3: `raw cmdline start 2048+0x80000+0x48 = 0x80848; len('debug=0xc serial=3 cpus=')=24;
  digit offset = 0x80860`. (The flashable pra-xnu.img gzip-compresses the payload
  at 0x800, so prefer the CMDLINE repackage over raw byte-poking.)
- Keep ALL other critical args, especially `pralog=1 praloglba=794623 wdt=-1`.
  python3: `p27 tail LBA 753664+49152-8193 = 794623` (ring is at the p27 TAIL, so
  it no longer destroys the boot image — PRA-LX1-noted.md:725-726's "test without
  pralog" advice is STALE on that point; still keep pralog). Battery >=25%, p27 only.

Run order (each is a falsifier):
1. **cpus=5** — selects logical 0..4 = cluster 0 + the **first** cluster-1 core
   (MPIDR 0x100). python3: `cpus=5 adds MPIDR 0x100 (FIRST cluster-1 core)`.
   - If cpus=5 panics with the same lock_ticket.c:143 / pset0+0x100 → the trigger
     is the **cluster boundary** (first cross-cluster registration), independent
     of core count. This is the expected result and isolates the bug to
     "registering a processor whose cluster_id != boot_cluster".
   - If cpus=5 boots 5/5 → the trigger is a *later* cluster-1 core or the count;
     escalate cpus=6,7,8 to find the first failing N.
2. **cpus=8** — reproduce the documented panic and capture the full early console
   (see capture note below) to confirm the owner thread / caller against the
   Phase-0 code reading.
3. **cpus=4** — re-confirm the proven baseline still boots 4/4 (regression guard).

Capture (IMPORTANT): the CPU bring-up and this panic happen **before the ring
starts**. VERIFIED: work/ring65-full.txt:1-2 begins `PRA LOG: lba=794623 ...` /
`[+ 30 s] pralog started`; pra_log_start prints that milestone
(pra_sdhci.c:1552-1575). No `A5XELTE CPU:` line appears in any work/ring*.txt
(grep: no matches) — the early bring-up is NOT in the ring. Therefore:
- **Primary capture = framebuffer console photo**, with `wdt=-1` so the panic
  stays on screen (this is exactly how the donor and the PRA trial captured it,
  A5XELTE_PROGRESS.md:88-94, PRA-LX1-noted.md:769-778). `a5fb_keep_on=1` keeps the
  panel up.
- Secondary = the panic-flush ring (patch 0156, pra_log_panic_flush writes the
  whole used in-memory ring on panic). UNKNOWN whether it contains pre-+30s
  lines; check the pulled ring after a panic, but do not rely on it for the
  early cluster-1 panic.

### Phase 2 — kernel patch to fix the cluster-1 registration panic (CI build)
This is the real work item. Candidate approaches, in order of preference:
1. **Instrument first** (one patch, marker assert per AGENTS.md): at the
   recursive-acquire site, log the calling thread, the lock owner, and a
   backtrace (reuse pra_log_panic_backtrace, pra_sdhci.c:1348) so the exact
   re-entrant acquisition is named. Add a boot-arg-gated trace around
   processor_startup pset_lock/unlock (processor.c:830-857) and processor_up
   (machine.c:187-203) keyed on `processor->cluster_id != boot_cluster`.
2. **Serialize / defer cluster-1 startup**: have startAll bring up all cluster-0
   CPUs first, publish, then start cluster-1 CPUs one at a time from a context
   that does NOT hold pset0.sched_lock across `cpu_start` (the current
   processor_startup already drops pset_lock before cpu_start at :857/:915 — so
   the re-entrancy is likely in the *secondary's* processor_up racing startAll,
   or in a clutch rebalance). A boot-arg `prampsleep=<ms>` between cluster-1
   starts is a cheap falsifier for a race.
3. **Fix the root cause** once named (cluster bookkeeping in
   ml_processor_register / pset node rebalance / clutch `pset_made_schedulable`).
   The donor SWEET never hit this (1 cluster); the fix must be guarded so it
   does not perturb the proven cpus=4 path.
- Build via CI only (RUNNER=macos-15 tools/pra_ci.sh), three-way patch verify,
  marker assert; package + flash per Phase 1 with the gate bypass for cpus=8.

### Phase 3 — sustained 8-core validation
- Falsifier in console/ring: `A5XELTE CPU: 8/8 CPUs initialized, SGI1 verified`
  (SweetCPU.cpp:210) and `cpu=4..7 mpidr=0x100..0x103 came alive; SGI1 OK`
  (SweetCPU.cpp:202), with NO lock_ticket panic.
- Then prove cluster 1 actually schedules: run the process sampler / a CPU-bound
  userland load and confirm threads run on logical 4..7 (the existing `SMP`
  sampler lines in ring65 are the process-sampler, NOT SMP evidence — do not
  confuse them). UNKNOWN until measured: whether the 2.1 GHz cluster gives the
  expected throughput gain.

### What could hang the boot (and the falsifier for each)
- cpus=1 → SMP boot never completes (VERIFIED). Avoid.
- Cluster-1 registration → lock_ticket.c:143 panic on pset0+0x100 (VERIFIED,
  the current blocker). Falsifier: cpus=5 reproduces it at the cluster boundary.
- `cpu=N startup timeout (reset/MMU/GIC/SGI)` (SweetCPU.cpp:198) → core powered
  but never reached initCPU: entry/MMU/GICv2 ordering or CNTVOFF skew. Falsifier:
  the `entered initCPU mpidr=... EL... IRQs=...` line (SweetCPU.cpp:250) absent.
- `PSCI CPU_ON rc=` non-zero (SweetCPU.cpp:350) → conduit/entry rejected (-3
  NOT_SUPPORTED, -4 INVALID_PARAMS). Not expected: rc=0 already seen for 0x1.
- `invalid GICv2 CPU%u target mask` (pe_fiq.c:313) → cluster-1 GICC not up.
- CNTVOFF skew on a cluster-1 core → that core's timer never fires → scheduler
  stall / startup timeout (INFERRED from the DREAMLTE precedent, A5XELTE.h:45-51).

### Flash-vs-offline summary
| Change | Needs flash? | Needs CI rebuild? |
|---|---|---|
| cpus=4→5/8 cmdline (gate bypass) | YES (p27) | NO (kernel already 8-capable) |
| ADT cpu nodes | NO change needed (already 8) | NO |
| Shim secondary release | NO change needed (XNU does PSCI) | NO |
| Instrument cluster-1 lock path | YES to observe | YES |
| Fix cluster-1 registration panic | YES to validate | YES |
| Source/ADT/board 8-capability audit | NO (offline, done) | NO |

## 6. Safety / do-not-do (AGENTS.md + handoff authoritative)
- Flash ONLY p27 via tools/pra_flash_skip.sh, readback-verified; never
  p30/p32/bootloaders/recovery/modem/persist/EFS/BOOT. Battery >=25%.
- Never boot without `pralog=1 praloglba=794623`. cpus≠4 requires
  `PRA_ALLOW_ANY_CMDLINE=1` (deliberate one-off) — keep the other 10 critical args.
- Serials via PRA_SERIAL only; no Apple binaries/device dumps in git.
- This scoping performed NO device access, NO flash, NO commits, NO file edits
  other than the parent saving this note. Durable numbers above were computed
  with python3 and quoted; claims labelled VERIFIED/INFERRED/UNKNOWN.

## 7. Ten-line summary
1. The XNU port, ADT and PRA board config are ALREADY 8-core/2-cluster capable
   (PRA.h:16, board_config.h:125-133, mkadt_pra.py:133-154; ADT verified 8 nodes).
2. The shim releases NO secondaries (start.S:21-46); XNU brings them up via PSCI
   CPU_ON SMC64 0xC4000003 (SweetCPU.cpp:40-51,349) — the exact stock DT cpu_on ID.
3. `cpus=N` is parsed in ml_parse_cpu_topology (machine_routines.c:957) and bounds
   the ADT cpu-node prefix; cpus=4 = cluster0 MPIDR 0..3, cpus=8 adds 0x100..0x103.
4. Stock hi6250 DT: 8 cores enable-method="psci", GICv2, virt timer 1.92 MHz;
   dmesg boots all 8 at EL1, MIDR 410fd034 = A53 r0p4 on every core.
5. Selecting 8 is a CMDLINE-ONLY change (digit at raw offset 0x80860); no kernel
   rebuild, no ADT/shim edit; gate needs PRA_ALLOW_ANY_CMDLINE=1.
6. BUT cpus=8 was already booted on PRA and PANICS: recursive ticket lock on
   pset0.sched_lock (pset0+0x100, lock_ticket.c:143) registering cluster 1
   (PRA-LX1-noted.md:769-795); identical on the Exynos donor (A5XELTE_PROGRESS.md:94).
7. PSCI works (CPU_ON rc=0); the blocker is the scheduler/processor-registration
   layer for the SECOND cluster, not PSCI/ADT/shim. Root cause UNKNOWN.
8. XNU has NO A53 errata workarounds (stock enables 7); low risk since cluster0 is
   the same A53 r0p4. Watch CNTVOFF skew on cluster-1 virt timer (DREAMLTE precedent).
9. The early panic is BEFORE the +30s ring start, so capture via FB console photo
   (wdt=-1, a5fb_keep_on=1); the pralog ring does not contain the bring-up lines.
10. Experiment: offline lock-path audit → flash cpus=5 (cluster-boundary falsifier)
    → cpus=8 reproduce → CI patch to instrument/serialize/fix cluster-1 registration
    → validate `8/8 CPUs initialized, SGI1 verified` + scheduling on logical 4..7.

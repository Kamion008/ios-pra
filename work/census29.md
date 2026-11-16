# census29.md — ring29 sampled-PC census (task A, 2026-11-16)

## Ruling

**"Majority trap -13 (task_dyld_process_info_notify_get)" is REFUTED.** The
handoff's raw-byte claim ("MOVN x16,#0xB; SVC; RET; MOVN #0xC; SVC; RET" at
file offset 0x5f69030) does not match the bytes. The dominant sampled PC is
**trap -47 = mach_msg2_trap**; zero of 537 samples sit at a -13 stub.

## Method (all arithmetic scripted; work/dscmap.py + work/census29_run.py)

- Cache re-extracted to ~/dsc-x/cache (43 files, 2.6 GB) from
  research/ipsw-x/087-86593-047.dmg via apfs-fuse mount ~/dsc-mnt (HOME, per
  instruction). Handoff §8's symbolizer scripts were GONE from work/ (lost
  with /tmp); rebuilt as work/dscmap.py.
- Mapping tables: subcache headers have mappingOffset/Count u32 at +0x10/+0x14
  and 32-BYTE mapping entries (48-byte stride misparses .27/.41). Self-test:
  vm 0x1c2611030 → subcache .19 @ file 0x5f69030 = the handoff anchor.
- Image tables (main file): A @0x1fd0, 2475 entries addr@+0, authoritative —
  libsystem_kernel.dylib @ 0x1c2610000 confirmed by Mach-O LC_ID_DYLIB; B
  @(+0x88,+0x90) = (0x15530, 2710) addr@+0x10 (lower region 0x1800b8000..) —
  B's path pool is UNRELIABLE (shifted names); names = Mach-O parsing only.
- Encodings derived from ARMv8 fields with runtime asserts: MOVN x16 =
  0x92800000|imm<<5|16, MOVZ x16 = 0xD2800010|imm<<5|16, SVC #0x80 =
  0xD4001001, RET = 0xD65F03C0. MOVN x16,#imm → x16 = ~imm = -(imm+1) (the
  handoff's "-imm" reading is WRONG); MOVZ → x16 = imm (BSD, no inversion).
- Saved-pc model (byte-verified): xnu stores pc = SVC+4 for a blocked thread:
  mach stubs = [MOVN@pc-8][SVC@pc-4][RET@pc]; BSD stubs = [MOVZ@pc-8][SVC@pc-4]
  [B.cond@pc]. In-flight = word at pc-8 (MOVN → -(imm+1); MOVZ → imm).

## Census (44 samples, 537 thread records; slides from the sampler's own
  lines: backboardd=SpringBoard=0x2e834000, Setup=0x9764000)

| unslide | n | class | trap/syscall | image |
|---|---|---|---|---|
| 0x1c2611030 | 268 (bbd 141, SB 107, Setup 20) | stub-mach | **-47 mach_msg2_trap** | libsystem_kernel |
| 0x1c26114f0 | 76 (bbd 40, SB 26, Setup 10) | stub-bsd | **368 workq_kernreturn** | libsystem_kernel |
| 0x1c2611ad0 | 27 (bbd 17, Setup 10) | stub-bsd | **515 sys_ulock_wait** | libsystem_kernel |
| 0x1c2611538 | 16 (SB) | stub-bsd | **375 kevent_id** | libsystem_kernel |
| 0x1e76e1030/4f0/ad0 | 64 (Setup) | NOT a stub (no SVC in ±region) | — none assigned | real code (poll/SIMD loops, region attr'd libtidy/MIL) |
| 0x1d3215030/4f0/ad0 | 60 (Setup) | NOT a stub | — none assigned | MIL region code |
| pc=0 | 22 | sampler could not read pc | — | — |
| singles (4) | 4 | sample-0 outliers + transients: libobjc.A.dylib+0xf180, /usr/lib/dyld text (both running), getdirentries64 ×1, open ×1 | 344 / 5 | — |

Parked structure (thread indices are per-sample enumerations; only parked
conclusions are meaningful): bbd t0 main: 17/19 at mach_msg2 (transients: objc,
getdirentries64); SB t0 main: 17/19 at mach_msg2 (+1 dyld, +1 open); bbd t2-t7
+ more: mach_msg2 17-18×; bbd t8-t12 + SB t12-t16: workq/ulock/kevent parks;
Setup t0-t3: ACTIVE (MIL/Metal grind), not stalled. Raw words: census29_full.json.

## Cross-checks (H5)

- Stub run decodes in exact table order: -44 task_name_for_pid … -47
  mach_msg2_trap -48 … -59 swtch_pri … (osfmk/kern/syscall_sw.c:105-198;
  mach_msg2 entry :154, arm64 #if branch; the duplicate "/* 47 */" is #else).
- mach_msg_trap (-31) stub at RET 0x1c2610f70 (MOVN x16,#30); NO sampled pc
  points at it (nearest sampled pc is 0xC0 past).
- Independent subagent (raw bytes only, no access to my analysis) decoded
  A=-47 mach_msg2_trap, B=368 workq_kernreturn, C=515 sys_ulock_wait and
  refuted the -46/-48 off-by-one alternates from the bytes. Refutation round:
  SURVIVED. My own pipeline produced identical words (spot-check).

## task_dyld_process_info_notify_get (osfmk/ipc/mach_kernelrpc.c:617-775, now read in full)

Can copyin/copyout: YES — mach_copyin of names_count (:638); copyoutmap_
atomic32 reset (:666); mach_copyout of count (:670) and names (:726,:732).
Locks: GLOBAL lck_mtx_lock(&g_dyldinfo_mtx) (:661, unbounded wait if any
process's dyld-notify op holds it), itk_lock(current_task()) (:662,
unbounded), plus ipc_port_copy_send_mqueue (:680) / ipc_port_copyout_send
(:708) port/mq locks and ipc_right_lookup_write space lock (:759 error path).
Unbounded waits: those locks + user-memory copyio (pager/IO on fault).
It does NOT block on any message receive. Zero ring29 samples sit here, so
H2 (deadlock inside this trap) has no supporting evidence.

## Implications (for 0173 and the handoff)

- All parked SpringBoard/backboardd threads wait on: Mach messages (mach_msg2,
  268/387 stub samples = 69% of parked), GCD workqueue parks (76), userspace
  locks ulock_wait (27), kevent (16). The stall reads as "main threads blocked
  in mach_msg2 (send/receive) while GCD workers idle" — the classic shape of a
  missing/never-replying peer service, not of a VM-map or dyldinfo deadlock.
- 0173 hunk (a) (mach_vm_deallocate probe) measures a trap that NEVER appears
  (0 of 537): drop it. Hunk (b) (kernel backtrace + thread state + wait
  event) is exactly the right tool and stays priority; its mach_msg2 wait
  will name the port/holder kernel-side.
- HANDOFF_2026-11-16.md §2/§3/§4 (incl. the "off-by-one → -13" refuted-theory
  entry) are invalidated by this census; H1 stays plausible, H2/H3 weakened,
  H4 untouched.

## Tooling notes for next session

- work/dscmap.py works: mappings, both image tables, Mach-O containment, stub
  decode, trap/BSD name tables. Extraction under $HOME (~/dsc-x/cache,
  ~/dsc-mnt), not /tmp. .symbols stays broken/unused; names = Mach-O parse
  (LC_ID_DYLIB), never table B's path pool (shifted/wrong).
- Sampler thread indices are per-sample; aggregate per-thread only for parked
  PCs. pc=0 rows (22) = unreadable state, not a trap.
- Setup's printed slide 0x9764000 IS its cache slide (0x1cbd75xxx pcs unslide
  exactly onto libsystem_kernel stub RETs); its 0x1f0e4xxxx pcs are real
  non-stub code (active MIL grinding).

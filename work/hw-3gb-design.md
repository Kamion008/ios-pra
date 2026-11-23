# hw-3gb-design — scoping more kernel-managed RAM on PRA-LX1 (2026-11-23)

Scope: give ported XNU more than the current 1 GiB. Read with AGENTS.md +
HANDOFF_2026-11-23d.md. Source: explore sub-agent (read-only), persisted by the
parent session. Labels: VERIFIED (file:line / quoted command), INFERRED
(reasoning from verified facts), UNKNOWN (needs a flash).
All arithmetic is python3, quoted inline.

## TL;DR (the decisive finding)

The phone's 3 GB is NOT one contiguous block. System RAM is 8 fragments
spanning 0x00400000..0xe0000000 with a 512 MiB non-RAM gap
0x60000000..0x80000000 and a 32 KiB hole at 0x87b00000. The largest
contiguous System RAM range is 0x87b08000..0xe0000000 = 1412.97 MiB.
boot_args carries ONE physBase/memSize pair, so:

- 2 GiB or 3 GiB in a single window is PHYSICALLY IMPOSSIBLE on this device
  (VERIFIED, §2/§3). No ADT value can do it.
- The cheap, no-kernel-rebuild win is 1 GiB -> 1.375 GiB
  (dram-size 0x40000000 -> 0x58000000, end 0xe0000000). Two files change;
  the bootstrap page tables still fit (7 of 8 pages, VERIFIED §3).
- 2-3 GiB total requires a multi-segment-DRAM kernel patch (boot_args,
  arm_vm_init, pmap/VM all assume one range) — real surgery, scoped in §4B,
  not a boot-arg experiment.

## 1. Why 1 GiB at 0x88000000 today

VERIFIED — the window base is forced by a RAM hole, the size was a
conservative first step:

- tools/mkadt_pra.py:65-76 (comment): the upper bank is
  0x80000000..0xdfffffff but /proc/iomem has a 32 KiB hole
  0x87b00000..0x87b07fff that is not System RAM; boot_args has one
  contiguous physBase/memSize pair, so the window starts above it at
  0x88000000 (2 MiB aligned). "1 GiB here (0x88000000..0xc8000000) is the
  first step up from the 512 MiB the donor used; the ceiling for this
  single window is 1.375 GiB. The bootstrap page tables are sized for
  2 GiB ... Keep in sync with RAM_END in shim/pra/boot_main.c."
- tools/mkadt_pra.py:77-78: dram-base = 0x88000000, dram-size = 0x40000000.
- shim/pra/boot_main.c:24-29: RAM_BASE 0x88000000, RAM_END 0xC8000000
  ("Ceiling for one contiguous window is 0xe0000000").
- History: PRA-LX1_PROGRESS.md:383-389 (512 MiB window 0x88000000..0xa8000000
  chosen over 0x80000000 because of the hole); PRA-LX1-noted.md:896-904 and
  git a58f3f5 "pra: grow the XNU window from 512 MiB to 1 GiB" — only
  mkadt_pra.py (dram-size) + boot_main.c (RAM_END) changed; "The bootstrap
  page tables already handle 2 GiB ... Ceiling for one window stays
  1.375 GiB."
- docs/pra-address-overrides.md:23-38 and docs/pra-facts-review.md:59-73
  (independent audit: hole is real, "0x80000000..0xdfffffff contiguous" is
  false by one hole; graphic/logo carveouts are lower-bank only).
- Motivation to grow: HANDOFF_2026-11-16b.md:226-227 lists "RAM window
  (1 GB ADT dram-size)" as a known lever "if memory pressure appears once
  more daemons run." (No recorded jetsam/OOM event was found in work/*.md —
  the pressure motivation is INFERRED, not a measured failure.)

`--highmem`: VERIFIED it does NOT exist in mkadt_pra.py (its argparse only
takes `output`, tools/mkadt_pra.py:258-264). It is a DONOR flag:
tools/mkadt.py:5,15-19,73 sets SWEET/S8 dram-base 0x100000000 / size
0xfcc00000 (the S8's contiguous high bank). PRA has no such bank (NOTES.md:208
is the S8 precedent; DREAMLTE_PROGRESS.md:25 likewise S8). Do not port
--highmem blindly: PRA's upper bank is only 1.5 GiB and split.

The shim does NOT build a block mapping. VERIFIED: shim/pra/start.S:4-7 runs
with MMU off ("Entered ... with MMU off"), shim/pra/xnu_jump.S:11-21 clears
SCTLR_EL1.M/C/I and branches to XNU physical==virtual. The "block mapping"
is XNU's OWN osfmk/arm64/start.s (§3). The loader only bounds-checks the
window (boot_main.c:177-182) and copies segments (boot_main.c:195-208).
xnu_boot.ld:13,44: loader linked at 0x480000, payload at __payload_start
0x500000. mkpayload.py:150-158 derives virt_base from __TEXT (32 MiB mask)
and phys_base/mem_size from the ADT (adt_dram, mkpayload.py:135-140), so the
loader and kernel cannot disagree on the window.

## 2. The REAL DRAM layout (stock captures)

VERIFIED — live/iomem.txt:1-10 (System RAM only):
```
00400000-0dffffff   0e001000-348fffff   34a78000-34a7ffff
34b20000-34efffff   35ec0000-35ffffff   3f100000-5fffffff
80000000-87afffff   87b08000-dfffffff
```
VERIFIED — live/dmesg.txt:254-269 (bootloader memblock regions, base/size):
(0x400000,0xdc00000) (0xe001000,0x268ff000) (0x34a78000,0x8000)
(0x34b20000,0x3e0000) (0x35ec0000,0x140000) (0x3f100000,0x20f00000)
(0x80000000,0x7b00000) (0x87b08000,0x584f8000).

python3 (quoted):
```
sum of System RAM regions = 3046240256 B = 2905.12109375 MiB = 2.8370323181152344 GiB
last region end = 0xe0000000 ; region6 end = 0x60000000
dmesg totalpages 743711 * 4096 = 3046240256 B  (matches sum? True)
dmesg Memory total 2974844K = 3046240256 B = 2.837 GiB; available 2666720K = 2.543 GiB
upper bank 0x80000000..0xe0000000 = 1536.0 MiB; hole 0x87b00000..0x87b08000 = 32768 B = 32 KiB
largest contiguous System RAM range 0x87b08000..0xe0000000 = 0x584f8000 = 1412.96875 MiB
gap 0x60000000..0x80000000 = 512.0 MiB NOT RAM
```
- live/dmesg.txt:30 "On node 0 totalpages: 743711"; :47 "Memory:
  2666720K/2974844K available (... 258972K reserved, 49152K cma-reserved)".
  The Android kernel saw ~2.84 GiB total / ~2.54 GiB available — consistent
  with 3 GB DRAM minus firmware carveouts and the 512 MiB address gap.
- live/dmesg.txt:2367 "mem_cfg: segment_num=2" — the bootloader describes 2
  DRAM segments (low 0x0..0x60000000, high 0x80000000..0xe0000000). INFERRED:
  this is why the single-window DTS node is wrong (below).

DTS caveat (VERIFIED discrepancy, do not trust the DTS memory node):
- pra-lx1-b412.dts:9887-9890 /memory@0 reg = <0x0 0x00400000 0x0 0xbfe00000>.
  python3: `0x400000+0xbfe00000 = 0xc0200000` — ends at 0xc0200000, NOT the
  0xe0000000 that iomem/memblock show. There is also an empty /memory node
  (dts:12861-12864, reg = <0 0 0>). INFERRED: the decompiled DTS memory node
  is a template the bootloader patches at boot (segment_num=2); the
  authoritative live map is iomem + memblock. (docs/pra-facts-review.md:127-133
  already warns this decompiled DTS has corrupted cells; use reg fields only.)

Carveouts (VERIFIED, pra-lx1-b412.dts:5575-5714) — ALL in the lower bank
(< 0x60000000), none in the XNU upper window:
- TEE/secure: bl31-s 0x35e00000+0xc0000 (:5661), secureos-s
  0x36200000+0x1e00000 (:5669), sensorhub-s 0x36000000 (:5665, reg cells
  corrupted), lpmx-core 0x34900000+0x100000 no-map (:5625).
- modem: modem-s 0x38000000+0x6c00000 no-map (:5673), modem-share
  0x3ec00000+0x500000 (:5677), modem-socp 0x3f100000+0x1000000 disabled
  (:5681), modem-log 0x40500000 disabled (:5686), xmode-data 0x43700000
  disabled (:5691).
- hifi/isp: hifi-data 0x34f00000+0x400000 (:5649), hifi-ipc 0x35300000
  (:5653), hifi-s 0x35400000+0xa00000 (:5657), isp-boot 0x34b00000 (:5640),
  ivp 0x34e00000 disabled (:5644), sensorhub-share 0x34a80000 (:5636).
- GPU: graphic 0x31000000+0x1a40000 (:5611-5612) = 26.6 MiB; the ADT records
  it as pra-gpu-mem (mkadt_pra.py:227-239) and the GPU drafts use it as
  scratch — it is BELOW dram-base 0x88000000 so XNU never allocates it.
- logo/splash: logo-buffer 0x5d000000+0x3000000 (:5706-5708) = 48 MiB; this
  is the live scanout (A5_FB_PHYS, PRA.h:47) — below the window, unaffected.
- CMA: cma_align2M 0x5c000000+0x1000000 (:5696, dmesg:27 16 MiB pool) and
  dmesg:29 "cma: Reserved 32 MiB at 0xde000000" (lower bank).
- ramoops/pstore: pstore-mem 0x34800000+0x100000 (:5620), ramoops node
  (:11382-11393) references it. mntndump 0xe000000+0x1000 no-map (:5599).
- The 0x87b00000 32 KiB hole is NOT in the DTS reserved-memory list;
  docs/pra-facts-review.md:69-70,170-171 calls its owner UNKNOWN
  (candidate hisi log/mntn). dmesg:268 "print_mb_cb->regions base is
  0x87b08000" is the memblock region AFTER the hole, not the hole's owner.

## 3. What constrains growing the window

(a) PHYSICAL CONTIGUITY — the binding constraint. VERIFIED §2: no contiguous
2 GiB range exists anywhere. python3:
```
2 GiB contiguous needs end-base=0x80000000; from 0x88000000 end would be 0x108000000 (> 0xe0000000 RAM end) -> impossible
max single window from 0x88000000 to 0xe0000000: size = 0x58000000 = 1408.0 MiB = 1.375 GiB
```
boot_args is single-window: pexpert/pexpert/arm64/boot.h:61-71 (one virtBase/
physBase/memSize/memSizeActual); boot_main.c:16-18 comment; arm_vm_init.c:1870-
1886 sets gVirtBase/gPhysBase/gPhysSize from that one pair, avail_end =
gPhysBase+mem_size (arm_vm_init.c:2003). INFERRED: 2-3 GiB therefore needs a
kernel change to describe a second range, not an ADT edit.

(b) XNU BOOTSTRAP PAGE TABLES (4K granule). VERIFIED constants:
- PRA uses 4K pages: MakeInc.def:345-349 (PRA -> -UARM_LARGE_MEMORY, link addr
  0xfffffff007004000); PRA.h defines neither __ARM_16K_PG__ nor ARM_LARGE_MEMORY
  (PRA.h:1-70; board_config.h:115-133 includes PRA.h, NOT A5XELTE.h/SWEET.h),
  so proc_reg.h:1157-1162 selects ARM_PGSHIFT 12. (The mkpayload.py:150-151
  "16K-granule L2 block" comment is donor-SWEET wording; the 32 MiB mask is
  just conservative alignment. INFERRED.)
- proc_reg.h:1217-1219 L1 entry = 1 GiB (shift 30); :1257-1260 L2 block =
  2 MiB (shift 21); :1444-1448 TTE_PGENTRIES = 4096>>3 = 512.
- pmap.h:108-116: BOOTSTRAP_TABLE_SIZE = ARM_PGBYTES*8 (non-LARGE_MEMORY).
  python3: `4096*8 = 32768 B = 8 pages`.
- start.s:573-575 reads virtBase/physBase/memSize; :651-674 slides the mapping
  start to the mach header (x18 = header_PA - physBase; x24 = memSize - x18);
  :704-710 builds V=P and KVA block maps; :712-732 (A5XELTE) maps A5_FB_2M_BLOCKS
  (=5, PRA.h:51) at 0x5D000000 in ONE extra L2 page (FB L1 index 1 != RAM L1
  index 2). :692-694 comment: "For a 2G 4k page device ... 1xL1 and up to 3xL2
  pages ... 8 total pages for V=P and KVA" (that worst-case assumes a large
  random slide and does NOT count the FB page).
- The actual slide is FIXED (mkpayload rebases to unslid VAs; no KASLR slide
  here): parsed from shim/pra/outxnu/payload.bin, __TEXT 0xfffffff007004000,
  virt_base 0xfffffff006000000 -> header offset 0x1004000.

python3 simulation of create_bootstrap_mapping (start.s:468-500), quoted:
```
budget: 2 L1 + 6 L2; A5XELTE FB takes 1 L2 -> 5 L2 for V=P+KVA
current 1 GiB          mem=0x40000000 num_ents= 503  V=P L2=2 KVA L2=2 FB L2=1  TOTAL=7 pages  OK <=8
max single 1.375 GiB   mem=0x58000000 num_ents= 695  V=P L2=2 KVA L2=2 FB L2=1  TOTAL=7 pages  OK <=8
hypoth 2 GiB           mem=0x80000000 num_ents=1015  V=P L2=3 KVA L2=3 FB L2=1  TOTAL=9 pages  OVERFLOW >8
hypoth 3 GiB           mem=0xc0000000 num_ents=1527  V=P L2=4 KVA L2=4 FB L2=1  TOTAL=11 pages  OVERFLOW >8
V=P start index = 72 -> first page holds 440 ; KVA start index = 56 -> first page holds 456
```
Precise fit threshold (python3): total stays <=8 up to num_ents=968
(mem_size ~ 0x7a004000 = 1.906 GiB); num_ents=969 (~1.908 GiB) overflows to 9.
So the mkadt "sized for 2 GiB" claim is approximately right for THIS fixed
slide (fits to ~1.9 GiB), but a true 2 GiB worst-case slide + FB would need 9.
VERIFIED conclusion: at the 1.375 GiB RAM ceiling the bootstrap uses 7/8 pages
— bootstrap is NOT the binding constraint; contiguity is. If a future multi-
window patch ever maps >1.9 GiB through start.s, BOOTSTRAP_TABLE_SIZE
(pmap.h:115) must grow first. Overflow victim: bootstrap_pagetables is a
SECURITY_READ_ONLY_LATE array (arm_vm_init.c:87); start.s bumping its freeptr
past 8 pages would stomp adjacent kernel globals before RO protection ->
early hang/corruption (INFERRED failure mode).
- The DEVELOPMENT/DEBUG guard at arm_vm_init.c:1966-1972 is INERT as written:
  it compares a page COUNT (pages_used = 2*(l1_entries+1), max ~10 here) to
  BOOTSTRAP_TABLE_SIZE in BYTES (32768). python3: `fires? False` for every
  case. Do not rely on it to catch an overflow (INFERRED, units mismatch).

(c) KERNEL VA SPACE — not binding. VERIFIED vm_param.h:233-236 (non-KTRR,
non-LARGE_MEMORY): VM_MIN_KERNEL_ADDRESS 0xffffffe000000000, VM_MAX
0xfffffffbffffffff; MACH_VM_MAX_ADDRESS_RAW 0xFC0000000 for A5XELTE
(vm_param.h:136-143). arm_vm_init.c:1896 panics if mem_size >= half the span.
python3: `VM_MAX-VM_MIN span = 0x1c00000000 = 112.0 GiB; half = 56.0 GiB;
3 GiB < half ? True`. The physmap slide (arm_vm_init.c:1813,1911, up to 1 GiB)
and 16 MiB alignment padding (:1825, = 8*2 MiB) are VA bookkeeping, fine.

(d) eMMC DMA — not binding below 4 GiB. VERIFIED pra_sdhci.c:2253-2297: SDMA
system-address register is 32-bit; the driver checks the bounce buffer is
page-contiguous, 4-byte aligned and `phys >> 32 == 0` before arming, else
falls back to PIO. The bounce buffers are kernel .bss (pra_emmc_multi_buf
[128*512] :250, pra_emmc_bounce[512] :2382, pra_log_ring[4 MiB] :295,
PRA_MULTI_MAX=128 :205, PRA_LOG_SIZE=4<<20 :210) — they sit inside the kernel
image and MOVE with the window automatically. python3: `SDMA 32-bit: window
end 0xe0000000 < 0x100000000 ? True`. (Only a move ABOVE 4 GiB would break
SDMA; this design never does.)

(e) iOS USERLAND — no hardcoded 1 GiB found. VERIFIED kern_mib.c:915-918
hw.memsize = max_mem_actual, :1003 hw.physmem = mem_size — both derived from
boot_args.memSize at runtime, so the userland sees the new size automatically.
Grep of xnu/patches for 0xc8000000/0xa8000000/1073741824/hw.memsize found no
window-end hardcode (0171's 0x40000000 is a USER VA range, unrelated).
UNKNOWN: whether any iPhone X daemon caches a memory-class expectation; no
evidence either way (unmodified userland, reads sysctl dynamically — INFERRED
benign). The GPU arena (0x31000000) and fbcon (0x5D000000) are below the
window and unaffected (mkadt_pra.py:197-239).

(f) PAYLOAD/ADT PLACEMENT — not binding. VERIFIED from payload.bin + python3:
```
header PA = 0x89004000 ; kernel_end PA = 0x8ace0000 ; kernel span 28.859375 MiB
adt_pa = 0x8ace0000 adt_size = 0x3248 ba_pa = 0x8ace4000 topOfKernelData = 0x8ace5000
free RAM after topOfKernelData (1 GiB window) = 979.10546875 MiB
free RAM after topOfKernelData (1.375 GiB window) = 1363.10546875 MiB
```
ADT/boot_args land just above the kernel (~0x8ace5000), far below any window
end; boot_main.c:210-215 placement check passes for 0xe0000000. A5_ENTRY_
MARKER_PHYS 0x8FF00000 (PRA.h:52) stays inside the window and above kernel_end.

## 4. Experiment design

### 4A. RECOMMENDED first step: 1 GiB -> 1.375 GiB (no kernel rebuild)

Changes (exactly two files, mirroring a58f3f5):
1. tools/mkadt_pra.py:78 dram-size 0x40000000 -> 0x58000000 (end 0xe0000000).
2. shim/pra/boot_main.c:29 RAM_END 0xC8000000 -> 0xE0000000UL.
   (boot_main.c:177-182 bounds check: mem_size 0x58000000 == RAM_END-phys_base
   0x58000000, passes the `>` test. VERIFIED by arithmetic.)
No XNU source change, no CI run: pra_package.sh:45 regenerates the ADT,
mkpayload.py:158 copies dram into the payload header, build-xnu.sh:18-21,64
rebuilds the loader LOCALLY with clang/ld.lld (aarch64-none-elf) and reuses
the existing CI kernel Mach-O (out/ci-0201/kernel.development.pra). The
kernel reads memSize from boot_args, so the same binary boots the new window.

Command line: UNCHANGED proven default (pra_package.sh:54) + the touch args
of the current milestone. Do NOT prune the 11 critical args (AGENTS.md:36-43).
No new boot-arg is needed for the window itself (there is no `memsize`
override in pexpert/osfmk — grep found none; the ADT is the only lever).
Keep pralog=1 praloglba=794623, wdt=-1, cpus=4.

Ordering:
1. OFFLINE: edit the two constants; run pra_package.sh; verify (§5 offline
   list). Confirm img <= 24 MiB (pra_package.sh:70-76) and the 11-arg gate.
2. Get explicit user approval (exact flash command shown) — AGENTS.md:72.
3. Flash ONLY p27 via tools/pra_flash_skip.sh, readback-verified; battery
   >=25%. Reboot.
4. Pull ring (tools/pra_readlog.sh), cmp vs previous ring first (AGENTS.md:32-34).

Ring-log falsifiers (pralog) and what each outcome means:
- Loader console/ring prints `phys 0x88000000` / `mem 0x58000000`
  (boot_main.c:191-193 con_hex). If instead `FAIL: window` -> RAM_END was not
  raised in the rebuilt loader (the two files drifted). FALSIFIER for the
  two-file sync.
- XNU early boot reaches the eMMC ring start (pra_log_start) and the usual
  `PRA eMMC:` / `BSD root: sdhcroot0` lines -> the window mapped and VM came
  up at 1.375 GiB. A hang BEFORE any ring text with the loader's "jumping to
  XNU" present = early MMU/bootstrap fault (would indicate the 0xc8000000..
  0xe0000000 region is not usable RAM at runtime — see UNKNOWN below).
- A panic screen `Unsupported memory configuration` (arm_vm_init.c:1897/1957)
  would mean a VA-space gate — NOT expected at 1.375 GiB (56 GiB gate); if it
  appears, something else changed.
- Userland reaches SpringBoard as in T21c; hw.memsize now 1408 MiB
  (kern_mib.c:915). Success = same boot milestone as T21c PLUS the larger
  mem_size in the early ring lines.
- If the boot reproduces T21c exactly but memory pressure symptoms persist,
  the pressure was not RAM-bound (INFERRED) — the lever is spent.

Failure modes ranked: (i) loader FAIL:window (sync bug, offline-caught);
(ii) instant reset / early hang = runtime TZ/XPU protection on
0xc8000000..0xe0000000 (UNKNOWN — iomem says System RAM but the SWEET highmem
precedent NOTES.md:208 warns "unknown runtime TZ/XPU protection ... instant
reset"; this is the one thing only a flash can answer); (iii) userland OOM
unchanged (not a regression, just no benefit); (iv) success.

### 4B. 2-3 GiB total: a kernel project, not a boot arg (scope only)

VERIFIED blockers: single-window boot_args (boot.h:61-71), single-range
gPhysBase/gPhysSize/avail_end (arm_vm_init.c:1870-1886,2003), and no
contiguous 2 GiB physical range (§2). To reach 2-3 GiB you must:
1. Add a second memory range to the handoff (extend boot_args or publish a
   /chosen/memory-map "DRAM" extra bank) and teach arm_vm_init/pmap/VM to
   manage two physical ranges (pv_head table, physmap aperture, avail lists
   are all sized/derived from the single mem_size today). INFERRED: this is
   the bulk of the work and touches core VM.
2. Pick lower-bank fragments that are free of firmware carveouts, e.g.
   0x3f100000..0x5c000000 (above modem-socp, below CMA/logo) or
   0x0e001000..0x34000000 (below bbox/pstore) — each needs its own
   carveout exclusion. UNKNOWN: runtime TZ ownership of those fragments.
3. If any single bootstrap-mapped range exceeds ~1.9 GiB, raise
   BOOTSTRAP_TABLE_SIZE (pmap.h:115) and re-verify the start.s page budget
   (§3b simulation) — a CI kernel rebuild.
Recommendation: do 4A first (cheap, reversible, offline-verifiable). Treat
4B as a separate funded item; do NOT attempt it by lying about dram-size
(a 0x80000000 size from 0x88000000 would map non-RAM 0xe0000000..0x108000000
and the 0x60000000 gap is not even reachable — instant reset, INFERRED).

## 5. Offline-verifiable vs needs-a-flash

OFFLINE (python3, no device — all done in this note):
- ADT parse: dram-base/size read back from the regenerated ADT
  (mkpayload.adt_dram path) — confirm 0x88000000/0x58000000.
- Payload header parse: virt_base/phys_base/mem_size/kernel_end/adt_off
  (struct at 0x10, mkpayload.py:11-21) — confirm mem_size 0x58000000 and
  segments unchanged vs the 1 GiB payload (only header+ADT differ).
- Bootstrap page simulation (§3b) — 7/8 pages at 1.375 GiB.
- Loader bounds arithmetic (boot_main.c:177-182,210-215) — passes.
- Image size <= 24 MiB and 11-arg cmdline gate (pra_package.sh:70-100).
- Bank/hole/carveout sums (§2) — already quoted.

NEEDS A FLASH (cannot be proven offline):
- That 0xc8000000..0xe0000000 is usable RAM at runtime with no TZ/XPU/secure
  world owner (iomem says System RAM; runtime protection UNKNOWN).
- That XNU actually boots and the userland runs at 1.375 GiB (ring + screen).
- Whether more RAM reduces any real memory pressure (no OOM baseline recorded).

## Anchor index (file:line)
mkadt_pra.py:65-78,77-78,197-239,258-264; boot_main.c:16-18,24-29,177-182,
191-193,195-208,210-215; xnu_boot.ld:13,44; start.S:4-7; xnu_jump.S:11-21;
mkpayload.py:11-21,135-140,150-158; pra_package.sh:45,54,66,68,70-100;
build-xnu.sh:18-21,64,101-104; PRA-LX1_PROGRESS.md:78-94,383-389;
PRA-LX1-noted.md:896-904; docs/pra-address-overrides.md:23-38;
docs/pra-facts-review.md:59-73,127-133,170-171; HANDOFF_2026-11-16b.md:226-227;
live/iomem.txt:1-10; live/dmesg.txt:27-30,47,254-269,268,2367;
pra-lx1-b412.dts:5575-5714,5611,5620,5661-5684,5696,5706,9887-9890,11382-11393,
12861-12864; mkadt.py:5,15-19,73;
CI tree /tmp/opencode/ci-tree-0201/src/xnu: PRA.h:8-23,47-52;
board_config.h:115-133; MakeInc.def:345-349; proc_reg.h:1157-1162,1217-1219,
1257-1260,1444-1448; pmap.h:108-116; start.s:468-500,573-575,651-674,692-694,
704-710,712-732; arm_vm_init.c:87,1813,1825,1870-1898,1904,1911,1934-1935,
1966-1972,2003,2019; vm_param.h:136-143,233-236; boot.h:61-71;
pra_sdhci.c:205,210,250,295,2253-2297,2382; kern_mib.c:915-918,1003.
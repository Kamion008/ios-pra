# PRA-LX1 hardware facts review (independent audit)

Audit date: 2026-11-09. Sources audited: `docs/pra-address-overrides.md`,
`PRA-LX1_PROGRESS.md`, `live/iomem.txt`, `live/kernel-config.txt`,
`live/dmesg.txt`, `../pra-ios-port/live/dts/pra-lx1-b412.dts`
(note: the DTS lives at `/home/kamion008/Ai/pra-ios-port/live/dts/`, not
under `ios-pra/`, despite what `pra-address-overrides.md` line 8 says).
No file outside this review was modified.

---

## 1. GIC: GICv2 @ 0xE82B0000, dist 0xE82B1000, CPU interface 0xE82B2000 — **OK**

- DTS `/interrupt-controller@e82b0000` (dts lines 5852–5863):
  `compatible = "arm,cortex-a9-gic"` (= GICv2),
  `reg = <... 0xe82b1000 ... 0x1000  0xe82b0000-free?? no: ... 0xe82b2000 ... 0x1000>`
  i.e. distributor `0xe82b1000` size 0x1000, CPU interface `0xe82b2000` size 0x1000.
- Vendor dmesg line 3344: `[io_resources_init], regs_info[3].reg_name[gic],
  reg_base[0x00000000e82b0000], reg_size[0x2000]` — the vendor maps the whole
  0xE82B0000..0xE82B2FFF block, consistent with dist at +0x1000 and CI at +0x2000.
- Bootloader log (dmesg 1574, 2421): `gic: ITLinesNumber is 0x0000000a` → 352 SPIs
  (INTIDs 32..383-1). SPI 137 (INTID 169) and the FB IRQs (SPI 0x113=275, INTID 307)
  are in range. No overflow.
- Nuance, not a contradiction: the GIC never appears in `/proc/iomem`
  (huawei io_resources unmaps it); absence there is expected, not evidence against.
- The `redistributor-stride = <0 0x30000>` property in the node is a stale GICv3-ish
  leftover; GICv2 ignores it, but do not copy it into any regenerated ADT.

## 2. Timer: 1.92 MHz, DTS 0x1d4c00 — **OK, but the "24 MHz" flag is resolved**

- Arithmetic confirmed: 0x1d4c00 = 0x1d4c × 0x100 = 7500 × 256 = **1,920,000**. Exact match.
- dmesg line 62: `Architected cp15 timer(s) running at 1.92MHz (virt).`
- Corroboration #2 (clock model): dmesg line 67 `Calibrating delay loop (skipped),
  value calculated using timer frequency.. 3.84 BogoMIPS (lpj=19200)`.
- Corroboration #3 (DTS, independent node): `/hrttimer_app@0xfff08000`
  also has `clock-frequency = <0x1d4c00>` (dts line 13183).
- The "usual 24 MHz (0x16e3600)" objection: a 24 MHz fixed clock **does** exist on
  this SoC (`/clocks@0/clk_fpga_24m`, dts line 6033), but it is a spare FPGA clock,
  not the arch timer. The arch timer reads CNTFRQ, which the stock kernel measured
  as 1.92 MHz. 1.92 MHz is unusual (tick = 0.52 µs) but it is triple-evidenced; it
  is not an error. Do not hardcode any 24 MHz-derived tick constant in the PRA
  board (sleep/wake deadlines,SET_TIMEBASE,_endOfInterrupt timing).
- Note: dmesg line 1480 `isp_local_timer = 19200000` (19.2 MHz) is a different
  clock for the ISP remote processor — do not confuse it with CNTFRQ.

## 3. eMMC: sdhci-arasan @ 0xFF390000, size 0x10000, SPI 137 — **OK (IRQ number rests on DT alone)**

- DTS `/sdhci@FF390000` (dts 9350–9373): compatible `"arasan,sdhci"`,
  `reg = <0 0xff390000 0 0x00010000>`, `interrupts = <0 0x89 4>` → 0x89 = **SPI 137**.
- iomem line 74: `ff390000-ff39ffff : mmc0` — one page-aligned 64 KiB window.
- dmesg 1349: `sdhci-arasan ff390000.sdhci: clk-ahb...`, probe succeeded
  (`sdhci_arasan_probe: done!`, line 1363). Kernel config has
  `CONFIG_MMC_SDHCI_OF_ARASAN=y` (line 3237).
- Caveat live-dmesg irq numbers are allocated, not SPI numbers (e.g. ttyAMA0
  prints `irq = 49` at dmesg 461). So dmesg cannot confirm "137"; the only source
  for SPI 137 is the DTB. Cross-check it in the shim (it already parses the DTB)
  or via ICC_IAR during an SDHCI probe.

## 4. RAM window 0x80000000..0xdfffffff (dram-size 0x60000000) — **WRONG as "contiguous"**

- iomem lines 9–10:
  `80000000-87afffff : System RAM` and `87b08000-dfffffff : System RAM`.
- **Hole: `0x87b00000-0x87b07fff` (32 KiB / 8 pages) is NOT System RAM** inside the
  proposed window. Everything else in 0x80000000..0xdfffffff is System RAM.
- dram-size arithmetic: 0x80000000 + 0x60000000 = 0xe0000000 (exclusive) →
  ends at 0xdfffffff. That part is correct. `dram-base 0x80000000` correct.
- The doc/progress claim "Upper bank 0x80000000..0xdfffffff (1.5 GiB) is contiguous
  System RAM" (PRA-LX1_PROGRESS.md line 43) is false by one hole. XNU must exclude
  0x87b00000..0x87b07fff from the physical free list, or the bootloader/log owners
  of that page (candidate: hisi log/mntn area) get stomped.
- Note also: the "graphic" carveout (0x31000000..0x32A40000) and logo buffer
  (0x5d000000..0x60000000) live in the LOWER bank only; they do not affect the
  XNU upper window. `hisi_cma` at 0x48000000 has `status = "disable"` (dts 5594).

## 5. SoC base model 0xE0000000 — **OK, all sums land**

Requested tuple `(0, 0xE0000000, 0x20000000)` → window 0xE0000000..0xFFFFFFFF
(exclusive end 0x100000000).

| Child reg offset | + 0xE0000000 | Live evidence | Match |
|---|---|---|---|
| 0x2B1000 (+0x1000) | 0xE82B1000 | DTS GIC dist (dts 5860), dmesg 3344 maps the enclosing 0xe82b0000+0x2000 | ✓ |
| 0x2B2000 (+0x1000) | 0xE82B2000 | DTS GIC CPU interface (dts 5860) | ✓ |
| 0x1DF02000 (+0x1000) | 0xFDF02000 | iomem 62 `fdf02000-fdf02fff : /amba/uart@fdf02000`; dmesg 461 ttyAMA0 PL011 rev2 | ✓ |
| 0x1F390000 (+0x10000) | 0xFF390000 | iomem 74; dmesg 1349 | ✓ |

No named device fails to land. Side checks: watchdog 0xE8A06000 (iomem 14, dts 5420),
DSS 0xE8600000 (dts 151 `dss_base_phy`) are also inside the window. The eMMC reg
size carried in the ADT table (`0x1F390000, 0x10000`) matches the DTS/iomem window.

## 6. 4K pages / 3-level tables — **OK**

- kernel-config.txt line 415: `CONFIG_ARM64_4K_PAGES=y` (16K/64K unset, 416–417).
- line 34: `CONFIG_PGTABLE_LEVELS=3`.
- Bonus consistency: line 418–420 `CONFIG_ARM64_VA_BITS_39=y`,
  `CONFIG_ARM64_VA_BITS=39` — matches the doc's 39-bit `MACH_VM_MAX_ADDRESS_RAW`
  and `ARM64_LINK_ADDR` claims (doc lines 39–40).

## 7. CPU topology 8× Cortex-A53, MPIDR 0..3 / 0x100..0x103 — **OK**

- DTS `/cpus`: cpu@0..3 with `reg = <0 0x0..3>` (dts 173, 189, 205, 222),
  cpu@100..103 with `reg = <0 0x100..0x103>` (dts 269, 285, 237, 253 —
  the decompiler lists cluster1 out of numerical order; benign).
- Cluster sizes: `#size-cells = <0x0>` with `cpu-clock = cpu-cluster.0` / `.1`.
- dmesg 272–290: all of CPU1..CPU7 booted secondary processor `[410fd034]`
  (Cortex-A53 r? rev); `Booting Linux on physical CPU 0x0` (dmesg 1).
- DTS cell format warning: `#address-cells = <0x2>` on /cpus — the MPIDR is the
  second cell of the 2-cell reg (hi cells 0). Adapters reading only cell 0 will
  get 0 for all CPUs; read cell 1.
- Cluster1 is mislabelled `"arm,cortex-a5x"` in the DTS (typo; same part).
- Dmesg capacity split (cpu0-3 = 659, cpu4-7 = 1024, dmesg 232–290) corroborates
  two clusters with different max frequencies, i.e. exactly the 4+4 layout.

## 8. All DTS-vs-live contradictions and DTS=/template defects found

1. **Doc's timer-PPI narrative is confused** (`pra-address-overrides.md` lines
   47–50: "Live DTS lists PPIs 10/11/13/14 … which is not the usual 27/30").
   PPI 13 (secure phys) / 14 (ns phys) / 11 (virt) / 10 (hyp) **is** the standard
   armv8-timer quadruple. The GICv2 INTID for the virtual timer is PPI 11 + 16 =
   **27**, which is exactly what the doc wants to assume. dmesg's `(virt)`
   annotation (line 62) says Linux runs on the virt timer. The premise of
   "not the usual" is wrong; only the TrustZone-group-routing uncertainty remains.
2. **Panel mismatch** is explicitly known (progress.md ~line 18–19) and stands:
   DTS `lcd_panel_type = "auo_otm1901a_5p2_1080p_video"` (dts 111) vs live
   `BOE_NT35596`. DTS is a template here; irrelevant for MMIO bring-up, relevant
   for any panel-specific tuning assumed from the DTS.
3. **The decompiled live DTS is corrupted in phandle/string cells** in several
   nodes (e.g. `/cpus/cpu@3` `clock-latency = "", "", "", " "` dts 231,
   phandles like `phandle = "", "", "", "#"` dts 247–248, 279, 295,
   `/reserved-memory/sensorhub-s` reg = `"...\"6\"..."` dts 5666,
   `idle-states/cluster-sleep-0` entry-latency `"...\"(\"..."` dts 370).
   reg/compatible/interrupts cells appear intact, so the audit above is
   unaffected, but this decompiled DTS must NOT be used as a compile/ADT base.
4. **Cluster1 compatible typo** `arm,cortex-a5x` (dts 236, 252, 268, 284).
5. **GIC node name vs reg**: node is `@e82b0000` but reg starts at 0xe82b1000;
   the 0xe82b0000 page belongs to the vendor GIC wrapper. Not a contradiction —
   but any code that maps "the node's base" by name will get 0xe82b0000, and
   reading dist/CI registers there will hit the back bucks wrong window. Use reg, not the name.
6. No other DTS-vs-dmesg/iomem conflicts: GIC, timer, UART, eMMC, watchdog,
   framebuffer MMIO, graphic/logo reserved regions all cross-check.

---

## Must fix before boot

1. **RAM hole**: exclude `0x87b00000-0x87b07fff` from the XNU physical window /
   freelist. "0x80000000..0xdfffffff contiguous" is false per `/proc/iomem`.
2. **Correct the timer-PPI claim** in `pra-address-overrides.md` (PPI 13/14/11/10
   is the standard quadruple; vtimer = PPI 11 → INTID 27) before the "assumed
   INTID 27" shortcut is committed as fact.
3. **Do not regenerate the ADT from the decompiled DTS** — its phandle and some
   numeric/string cells are corrupted; only copy specific reg/compatible fields.
4. **No 24 MHz tick constants anywhere in the PRA board target**: CNTFRQ is
   1,920,000 Hz (dmesg + DTS ×2). Any sleep/wake/deadline math inherited from
   Samsung donor constants must be recomputed for 1.92 MHz.
5. **SP-based MPIDR extraction**: /cpus reg is 2 cells; MPIDR is the *second*
   cell. A generator that reads the first cell will produce 8 identical CPUs.
6. **GIC: trust reg, not the node name** (dist 0xe82b1000, CI 0xe82b2000; the
   @e82b0000 name page is a vendor block). Also drop `redistributor-stride`
   from any copied GIC node.

## Verify on hardware

1. Virtual timer INTID via ICC_IAR1_EL1 in the shim (expect 27; also confirm the
   TrustZone group split doesn't mask it — the shim/PPI is Huawei, like SWEET).
2. SPI 137 = eMMC interrupt: confirm via shim's DTB parse (irq[0] == 0x89) or an
   SDHCI probe interrupt.
3. MPIDR of the running CPUs (expect 0..3 / 0x100..0x103) and PSCI `cpu_on`
   MPIDR argument format against the live DTB.
4. Ownership/content of the 0x87b00000 hole (whoever it is: log buffer, mntn):
   confirm it is safe to exclude and that nothing critical was overlooked.
5. Watchdog disable actually holds (previous boot looped; the "improved" shim
   revision with watchdog kick + DSS fallback has not been flashed yet).
6. On the new revision: which painted window wins (blue 0x31000000 vs red
   0x5D000000 vs magenta DSS-referenced) — the framebuffer override TODO in
   pra-address-overrides.md depends on it, and the dmesg evidence already points
   at 0x5d000000 (`g_logo_buffer_base = 0x5d000000`, dmesg 837; bootloader
   `lcd_dispbuf:0x5d000000`, dmesg 2228 — both inside the 0x3f100000-0x5fffffff
   System RAM region, so it is RAM on this device).

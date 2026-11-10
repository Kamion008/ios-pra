# PRA address overrides inherited from A5XELTE

The PRA board defines `PRA`, `SWEET` and `A5XELTE` so it reuses the donor's
Cortex-A53 / GICv2 / 4K-page code paths. Those paths contain hardcoded Exynos
addresses. Every one below must be overridden with `#if defined(PRA)` (or a
PRA-specific ADT value) before a PRA kernel is trusted.

Live sources: `ios-pra/live/` (TWRP dmesg, iomem, kernel config), live DTS
`pra-ios-port/live/dts/pra-lx1-b412.dts`.

## ADT / SoC base model

`pe_arm_get_soc_base_phys()` returns the **parent base** of `arm-io.ranges`.
Every `arm-io` child `reg` is an **offset** from that base (`soc + reg[0]`).

| ADT property | A5XELTE | PRA |
|---|---|---|
| `arm-io.ranges` | `(0, 0x10000000, 0xf0000000)` | `(0, 0xE0000000, 0x20000000)` |
| `gic.reg` | `0x0c01000, 0x1000, 0x0c02000, 0x1000` | `0x82B1000, 0x1000, 0x82B2000, 0x1000` |
| GIC physical | `0x10C01000 / 0x10C02000` | `0xE82B1000 / 0xE82B2000` |
| `uart0.reg` | n/a | `0x1DF02000, 0x1000` -> `0xFDF02000` |
| `pra-emmc.reg` | `0x13540000, 0x2000` (Exynos) | `0x1F390000, 0x10000` -> `0xFF390000` |
| `dram-base` | `0x80000000` | `0x88000000` (above the 32 KiB hole) |
| `dram-size` | `0x20000000` | `0x20000000` (512 MiB, to `0xa7ffffff`) |

**RAM hole (handled by moving the window).** `/proc/iomem` splits the upper
bank:

```
80000000-87afffff : System RAM
87b08000-dfffffff : System RAM
```

`0x87b00000-0x87b07fff` (32 KiB, 8 pages) is **not** System RAM. XNU's
`gDramBase`/`gDramSize` is a single contiguous window, so the PRA ADT starts
the window at `0x88000000`, above the hole, instead of trying to carve it out
of the VM free list. The loader's `RAM_BASE`/`RAM_END` and the ADT values must
stay in lockstep; `mkpayload.py` reads them from the ADT, so they cannot drift.
| `timebase-frequency` | `26000000` | `1920000` (live dmesg) |

## Hardcoded values to override

| Component | Patch | A5XELTE value | PRA value | Status |
|---|---|---|---|---|
| Early framebuffer | 0090 `A5_FB` | `0x67000000` | `0x5D000000` (logo buffer) | CONFIRMED 2026-11-09: red flood |
| Early text | 0092 | `0x67000000` | `0x5D000000` | CONFIRMED (same buffer) |
| Screen stages | 0091 | `0x670a08c0`, `0x670c24c0`, `0x670e40c0` | logo-buffer equivalents | TODO |
| DECON checkpoints | 0089 | `0x6705d0c0`, `0x6707ecc0` | logo-buffer equivalents | TODO |
| eMMC GPT probe | 0104 | `0x13540000` | `0xFF390000` | TODO |
| 4K entry marker | 0082 | `0x469ff100` (Samsung log RAM) | PRA preserved RAM (TBD) | TODO |
| Virtual timer INTID | 0086 / `A5XELTE_VTIMER_INTID` | 27 | 27 (assumed) | VERIFY on hardware |
| CPU topology | 0101 | 1 boot CPU, 1 cluster | 8 CPUs, 2 clusters (MPIDR 0-3 / 0x100-0x103) | TODO |
| `ARM64_LINK_ADDR` | 0093 | `0xfffffff007004000` | same (generic 39-bit VA) | OK |
| `MACH_VM_MAX_ADDRESS_RAW` | 0084 | `0x0000000FC0000000` | same | OK |

## Open hardware questions

1. **Real scanout base.** The diag shim paints `0x5D000000..0x60000000` red and
   `0x31000000..0x32A40000` blue; the screen result decides the value. The
   bootloader log says `lcd_dispbuf:0x5d000000`, logo data at `0x5dfd2050`.
2. **Virtual timer INTID = 27.** Live DTS lists the standard armv8-timer PPIs
   10 (hyp) / 11 (virt) / 13 (secure phys) / 14 (ns phys). GICv2 INTID for the
   virtual timer is PPI 11 + 16 = **27**, and dmesg runs Linux on the virt timer
   (`Architected cp15 timer(s) running at 1.92MHz (virt)`), so 27 is the right
   default. The only open question is the TrustZone group split (Huawei, like
   SWEET, may route the NS timer differently); confirm with `ICC_IAR1_EL1`.
3. **Button GPIOs.** PRA has power + volume only; the A5XELTE home-button mapping
   does not apply.
4. **4K entry marker address.** Must be a RAM address the bootloader does not
   reuse; pick after the RAM-map review.

## Stage A definition of done

- [ ] `tools/mkadt_pra.py` produces a serialized PRA ADT.
- [ ] `0125-pra-board-target.patch` adds `PRA.h`, `board_config.h`,
      `Makefile`, `MakeInc.def`, `config/MASTER.arm64.pra`.
- [ ] PRA overrides for framebuffer and eMMC addresses are in a follow-up patch.
- [ ] `MACHINE_CONFIG=PRA` builds on a macOS runner (GitHub Actions).
- [ ] Kernel artifact named `kernel.development.pra` is produced.

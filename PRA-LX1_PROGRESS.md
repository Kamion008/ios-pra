# PRA-LX1 (hi6250 / Kirin 655) port progress

Target: Android boot image → EL1 diagnostic shim → XNU → iPhone X iOS 16.7.16 userland,
on the bootloader-unlocked Huawei PRA-LX1. Donor tree: `ios-galaxy-s8` (A5XELTE/SWEET).

This file records PRA-specific evidence. It does not change any Samsung claim.
Keep device dumps, serial numbers and downloaded Apple binaries out of git.

## Live hardware facts (TWRP 3.5.2_9-0, stock kernel 4.4.23+, 2026-11-09)

Collected over ADB root in TWRP. Source files were temporary
(`/tmp/opencode/twrp-inspect/live/`), not committed.

### Display
- `hisifb0`, `/sys/class/graphics/fb0` dev 29:0
- mode `U:1080x1920p-0`, `bits_per_pixel=32`, `stride=4320` bytes,
  `virtual_size=1080,3840` (double-height buffer)
- `lcd_model=BOE_NT35596 5.2' VIDEO TFT 1080 x 1920`
  (the DTS template names `auo_otm1901a_5p2_1080p_video`; the live panel is BOE)
- `/reserved-memory/graphic` in the live DTS:
  `reg = <0x00000000 0x31000000 0x00000000 0x01a40000>`
  (0x31000000..0x32A40000, inside System RAM)
- `/framebuffer@E8600000` is the DSS MMIO window (`dss_base_phy=0xe8600000`),
  **not** a RAM framebuffer

### UART
- live `/proc/iomem`: `/amba/uart@fdf02000` → PL011 at `0xFDF02000`
  (matches the shim's `UART_BASE`; no external access, screen is the only output)

### RAM map (live `/proc/iomem`, System RAM only)
```
00400000-0dffffff
0e001000-348fffff
34a78000-34a7ffff
34b20000-34efffff
35ec0000-35ffffff
3f100000-5fffffff
80000000-87afffff
87b08000-dfffffff
```
- `0x60000000` is **not** RAM (gap 0x60000000..0x7fffffff). Any plan that put the
  XNU window at `0x60000000` is wrong for this device.
- Upper bank `0x80000000..0xdfffffff` (1.5 GiB) is the natural XNU physical
  window candidate, but it is **not fully contiguous**: `0x87b00000..0x87b07fff`
  (32 KiB) is missing from System RAM and must be carved out of XNU's VM free
  list (see `docs/pra-facts-review.md`).

### Storage / partitions
- TWRP has no `/dev/block/by-name`; use numbered nodes.
- `mmcblk0p30` = `kernel` partition, 24 MiB (matches the stock kernel dump).
- Stock `kernel` boot image: `ANDROID!`, `kernel_size=0xb32b40`,
  `kernel_addr=0x480000`, gzip kernel, AVB descriptor after the kernel
  (`avbtool 1.0.0`, sha256).
- Stock kernel backup (outside git): `/mnt/giochi/pra-lx1-handoff/dump/mmcblk0p30.bin`,
  sha256 `1f84618832688868e094d1c35f490877603a755317ffc91be4888fed46075d56`.
- TWRP lives in `recovery_ramdisk` (ramdisk-only image, `kernel_size=0`).
- Stock kernel has no `CONFIG_KEXEC`, so TWRP cannot kexec an OS.

### Bootloader
- `bootlock=unlocked`, `userlock=unlocked`, `verifiedbootstate=ORANGE`
- fastboot allowlist includes `flash:kernel`, `flash:ramdisk`,
  `flash:recovery_ramdisk`; `fastboot boot` is blocked.
- `fastboot flash kernel` accepts the diagnostic image (AVB footer warning is
  expected; unlocked state skips verification).

## Diagnostic shim (`shim/pra`)

Build: `shim/pra/build.sh` (clang + ld.lld, no aarch64-gcc).
`out/pra-diag.img` is an Android boot.img v0 whose kernel is gzip(arm64 Image),
header copied from the stock page (kernel_addr 0x480000, page 0x800).
Verified: `ARMd` at 0x38, `text_offset 0x80000`, `image_size` aligned,
`msr DAIFSet` at 0x40.

What the diagnostic does now:
1. PL011 output at 0xFDF02000 (not externally visible).
2. Parses the live DTB passed by the bootloader (chosen/memory/psci/timer/GIC/
   sdhci/uart/graphic/hisi_cma/framebuffer nodes).
3. Dumps GIC and DSS/MMBUF/PCTRL register windows.
4. Disables the bootloader watchdog (`/amba/watchdog0` @ 0xE8A06000).
5. Scanout test: floods the whole graphic carveout
   (0x31000000..0x32A40000) blue and the logo window
   (0x5D000000..0x60000000) red, then repaints any page-aligned
   display-range address found in the DSS register window magenta
   (fallback for a scanout base outside the two known windows).
6. Reads GPT over SDHCI (read-only CMD17).

### Test history
- `pra-diag.img` (single-frame fills, no watchdog handling) flashed to `kernel`:
  phone showed the bootloader "your device is booting now" screen, then
  reset/looped. The stock kernel backup was not touched.
- Cause hypothesis: the shim never returns and never kicks Huawei's watchdog;
  the reset loop is consistent with a watchdog timeout. The scanout base was
  also not one of the two painted first frames.
- Next revision (built) floods whole regions, disables the watchdog, and adds
  the DSS-register fallback. Not yet flashed at the time of writing.

## Host helper
- `tools/notify.sh [short|long]` plays a host alert when the human must act on
  the phone (PulseAudio `paplay`).

## Stage A: XNU source integration (in progress, 2026-11-09)

Live facts re-harvested into `live/` (gitignored) after a host restart:
- `CONFIG_ARM64_4K_PAGES=y`, `CONFIG_PGTABLE_LEVELS=3` — same page model as
  A5XELTE, so the donor 4K entry path applies.
- eMMC is `sdhci-arasan` at `0xFF390000` (SPI 137), not the Exynos `0x13540000`.
- GICv2 at `0xE82B1000`/`0xE82B2000`; arch timer runs at **1.92 MHz**
  (dmesg: "Architected cp15 timer(s) running at 1.92MHz").
- PSCI v0.1 SMC conduit; 8x Cortex-A53 in two clusters
  (MPIDR `0-3` and `0x100-0x103`).

Donor baseline reconstructed locally:
- `xnu-src/` = `xnu-8796.141.3` (shallow clone, gitignored) + 122/124 donor
  patches. `0031-sweet-read-write-root.patch` and
  `0041-sweet-hfs-link-notes.patch` do not apply because the donor tree ships
  only `bsd/sweet_hfs/sweet_hfs_iokit.c` and `sweet_hfs_compat.h` (no
  `core/`). They are unrelated to entry/boot.
- Baseline commit: `donor: apply 122/124 ios-galaxy-s8 patches ...`.

Stage A artifacts:
- `docs/pra-address-overrides.md` — every inherited Exynos address that PRA
  must replace (framebuffer `0x67000000` -> `0x5D000000`, eMMC
  `0x13540000` -> `0xFF390000`, GIC offsets, timer INTID, topology).
- `docs/pra-facts-review.md` — independent audit of the live facts. Key
  correction: the upper RAM bank has a 32 KiB hole at
  `0x87b00000..0x87b07fff`; timer PPI 11 -> GIC INTID 27 is the standard
  mapping, not an anomaly.
- `tools/mkadt_pra.py` — PRA ADT generator (SoC base `0xE0000000`, GIC
  offsets `0x82B1000/0x82B2000`, DRAM `0x80000000+0x60000000`,
  timebase 1.92 MHz, 8 CPUs, `pra-fbcon`, `pra-emmc`). Produces a 9,680-byte
  ADT.
- `xnu/patches/0125-pra-board-target.patch` — `PRA.h`, `board_config.h`,
  `Makefile`, `MakeInc.def`, `config/MASTER.arm64.pra`. `PRA.h` defines
  `PRA`, `SWEET` **and** `A5XELTE` (shared Cortex-A53/GICv2 paths), 8 CPUs,
  vtimer INTID 27, and the `A5_*` framebuffer/entry-marker constants.
  Verified to apply forward on baseline `1ac0734`.
- `xnu/patches/0126-pra-fbcon-node.patch` — `pe_serial.c` binds the console
  to the ADT node `pra-fbcon` instead of `a5xelte-fbcon`. Verified to apply
  after 0125.

Build gate: no local macOS toolchain. Stage A needs a macOS runner
(`.github/workflows/xnu.yml`, `MACHINE_CONFIG=PRA`, Cortex-A53 flags) or a
Mac. `gh` is not installed on this host, so CI needs a repo/remote first.

## Next actions
1. Set up the PRA build: workflow `machine_config=PRA` with the Cortex-A53
   flags used for A5XELTE; produce `kernel.development.pra`.
2. Flash the improved `out/pra-diag.img` to `kernel`, boot, and read the
   screen (blue = `0x31000000`, red = `0x5D000000`, magenta = DSS-referenced).
   Restore the stock kernel from the verified backup afterwards.
3. Feed the confirmed scanout base into the PRA framebuffer override, then
   start stage B (first XNU boot with the PRA ADT).
4. Before trusting XNU with all 1.5 GiB, carve the `0x87b00000` 32 KiB hole
   out of the VM free list (see `docs/pra-facts-review.md`).

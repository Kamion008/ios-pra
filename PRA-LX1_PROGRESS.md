# PRA-LX1 (hi6250 / Kirin 655) port progress

Target: Android boot image → EL1 diagnostic shim → XNU → iPhone X iOS 16.7.16 userland,
on the bootloader-unlocked Huawei PRA-LX1. Donor tree: `ios-galaxy-s8` (A5XELTE/SWEET).

This file records PRA-specific evidence. It does not change any Samsung claim.
Keep device dumps, serial numbers and downloaded Apple binaries out of git.

## ⚠️⚠️⚠️ THE PRA BOOT COMMAND LINE — DO NOT SKIP, SHORTEN, OR "SIMPLIFY" ⚠️⚠️⚠️

Every PRA kernel flash MUST use this EXACT cmdline. It is the string of every boot
that reached the daemons (0153 → 0156 → 0158b; transcript line 1343). It is now the
DEFAULT in `tools/pra_package.sh` (no CMDLINE env needed), and both
`tools/pra_package.sh` and `tools/pra_flash_skip.sh` REFUSE an image that is missing
the 12 critical args — because every dropped arg below has a REPRODUCED phone
failure. Deliberate experiments bypass the flash gate with
`PRA_ALLOW_ANY_CMDLINE=1`, nothing else.

THE CMDLINE (one line, copy-paste verbatim):

```
debug=0xc serial=3 cpus=4 keepsyms=1 rd=sdhcroot0 emmcroot=userdata emmcprobe=1 emmcwrite=1 rootrw=1 unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 emmcstats=1 emmcmulti=0 pralog=1 praloglba=794623 sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1 sweetfb_hz=1
```

What breaks without each critical arg — all observed on the PRA-LX1:
- **`cpus=4`** — `cpus=1` (the OLD package default!) hangs the SMP boot.
- **`emmcmulti=0`** — multi-block reads hit `PRA eMMC: card busy, skip read` →
  root mount error (2026-11-14, first 0159 boot — the incident that mandated this
  block). Driver comment: "emmcmulti=0 forces the per-sector path without a rebuild".
- **`pralog=1 praloglba=794623`** — without them there is NO eMMC ring: every boot's
  evidence, including the panic backtrace capture, is lost. `praloglba` points the
  ring at the erecovery_kernel tail so the next power-on still boots.
- **`wdt=-1`** — the watchdog reboots the panic off the screen before a photo.
- **`rd=sdhcroot0 emmcroot=userdata emmcprobe=1`** — no root device otherwise.
- **`emmcwrite=1 rootrw=1`** — ring flushes and writable root depend on them.
- **`emmcstats=1`** — the `PRA eMMC:` IO stats that expose controller stalls.
- **`wdt_test=no_user_checkin`** — companion to `wdt=-1`.
- **`sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1 sweetfb_hz=1`** —
  framebuffer console keep-alive (the on-screen capture path).
- **`unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1`** —
  boot progress args from the working boots; do not prune.

The old trap: `pra_package.sh` used to default to `cpus=1 … -noprogress`, and
hand-written CMDLINE overrides kept losing args (the 2026-11-13 handoff command
block itself had a lossy short version — the 2026-11-14 boot failed on the phone
because of it). The default is now the proven string and both scripts gate on it.
Do not weaken the gates.

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
- Bootloader splash backing store, confirmed from the kernel log line
  `hisi_fb_probe: g_logo_buffer_base = 0x5d000000, g_logo_buffer_size = 0x3000000`
  and `/reserved-memory/logo-buffer`:
  `reg = <0x00000000 0x5d000000 0x00000000 0x03000000>`
  (0x5D000000..0x60000000, 48 MiB, inside the lower System RAM bank).
  The earlier shim flooded this range plus the `graphic` carveout and the
  screen did not change; that run is now attributed to the SDHCI bug below,
  not to a wrong scanout address.

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

#### kexec on the newer hi6250 kernels (verified 2026-11-09, GitHub API only)

The stock 4.4.23 tree (`/home/kamion008/Ai/huawei/hi6250-kernel`, and the LineageOS
source `kernel/huawei/hi6250-8`) cannot get kexec: it has the generic
`kernel/kexec*.c` but **no `arch/arm64/kernel/machine_kexec.c`**, and arm64
kexec support only landed in Linux 4.6. Flipping `CONFIG_KEXEC` there would
not link.

`Iceows/android_kernel_huawei_hi6250` (fork, 1.4 GiB) has six branches, and
**every one of them has the arm64 kexec backend**:

| Branch | Kernel | Defconfig | `CONFIG_KEXEC` |
|---|---|---|---|
| `Phenix-4.9.337` (default) | 4.9.337 | `phenix_defconfig` | not set |
| `OSS` | 4.9.337 | `phenix_defconfig` | not set |
| `TEEOS` | 4.9.337 | `phenix_defconfig` | not set |
| `android-14` | 4.9.337 | `phenix_defconfig` | not set |
| `lineage-16.0` | 4.9.148 | `merge_hi6250_defconfig` | not set |
| `lineage-17.1` | 4.9.148 | `merge_hi6250_defconfig` | not set |

All six contain `arch/arm64/kernel/machine_kexec.c` (`machine_kexec`,
`machine_kexec_prepare`, `machine_kexec_cleanup`, `machine_crash_shutdown`,
`cpu_soft_restart`) plus `arch/arm64/kernel/relocate_kernel.S` and
`arch/arm64/kernel/cpu-reset.S`/`cpu-reset.h`. `arch/arm64/Kconfig` declares

```
config KEXEC
        depends on PM_SLEEP_SMP
        select KEXEC_CORE
```

`merge_hi6250_defconfig` and `phenix_defconfig` both set
`CONFIG_SMP=y CONFIG_HOTPLUG_CPU=y CONFIG_PM_SLEEP=y CONFIG_PM_SLEEP_SMP=y`,
so the only dependency is already satisfied: adding `CONFIG_KEXEC=y` to the
defconfig is the whole change. Neither branch has a `CONFIG_KEXEC_FILE`
backend (`arch/arm64/kernel/kexec_image.c` is absent), so use the
`kexec_load` syscall, not `kexec_file`.

Both trees also carry the drivers our XNU port must match:
`CONFIG_MMC_SDHCI_OF_ARASAN=y` (the Arasan SDHCI at `0xFF390000`) and
`CONFIG_HISI_FB_6250=y` (`hisifb` display). No release assets and no tags, so
there is no prebuilt Image to download: using any of them means building.

Conclusion: kexec is a **one-line enable on a buildable 4.9 tree**, but it is
an iteration-speed device, not a prerequisite. The p30 route already executes
our code, and XNU still has to be built on macOS CI either way.

#### CI build gates for `MACHINE_CONFIG=PRA` (fixed 2026-11-09)

`0125` added PRA to `SUPPORTED_ARM64_MACHINE_CONFIGS`, `MACHINE_FLAGS_ARM64_PRA`
and the arm64/arm64e selection, but four make gates and the three staging
scripts still accepted only `SWEET A5XELTE`. With `MACHINE_CONFIG=PRA`:

- the three `xnu/patches/*.sh` stagers exited 0, so `bsd/pthread/sweet_libpthread`,
  `libkern/crypto/sweet_bearssl` and `bsd/sweet_hfs` were never created;
- `bsd/conf/Makefile.template` and `libkern/conf/Makefile.template` did not
  point at those providers;
- `makedefs/MakeInc.def` did not apply the 39-bit compact kernel VA layout
  (4 KiB pages need it);
- and every C file guarded by
  `#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)`
  compiled to nothing, because `MACHINE_FLAGS_ARM64_PRA` defines only
  `ARM64_BOARD_CONFIG_PRA`. That failure is **silent**: the kernel links
  without the early console, built-in pthread, portable AES, UFS/eMMC drivers
  and the rest of the shared bring-up code.

Fixed by `xnu/patches/0127-pra-shared-build-gates.patch`:

- `PRA.h` defines `ARM64_BOARD_CONFIG_A5XELTE`, so PRA builds exactly the
  A5XELTE code generation; SWEET-only blocks stay off, as they do on A5XELTE,
  and board addresses still come from `PRA.h` (not `A5XELTE.h`);
- the two provider gates and the 39-bit VA gate include PRA;
- the three stagers accept PRA;
- `PRA.h` sets `A5_KEYS_DEFAULT`/`A5_TOUCH_DEFAULT` to 0, because those
  drivers compile for every `ARM64_BOARD_CONFIG_A5XELTE` board but poll
  Exynos7580 pins.

Verified locally: `git apply --check` passes and every gate now reads PRA.

Note: the local `xnu-src` tree has no `bsd/sweet_hfs` because the stagers were
never run here (they need macOS `xcrun` and network). `0031`/`0041` being
skipped locally is therefore a local artifact; in CI, `0026` runs first and
stages the files, after which `0031`/`0041` should apply.

Next audit (not done): PRA now compiles the A5XELTE-guarded Samsung drivers
(`bsd/dev/a5xelte_emmc.c`, `a5xelte_keys.c`, `a5xelte_touch.c`,
`bsd/dev/sweet_ufs.c`, `bsd/dev/sweet_sample.c`). Confirm each is
boot-arg/ADT-gated and cannot auto-probe Huawei hardware at boot.

#### Board-flag audit and two boot-breaking fixes (2026-11-10)

PRA now compiles the A5XELTE C paths (0127), so the flags and the guarded
drivers were audited against the known-good A5XELTE build.

1. **PAN.** `0125` set `__ARM_PAN_AVAILABLE__` to 1. Cortex-A53 is ARMv8.0 and
   has no PAN, so the `msr pan, #1` emitted by `arm_init()`/`arm_init_cpu()`
   is an undefined instruction and faults before the console can print. The
   donor fixed the same fault for A5XELTE in `0095-a5xelte-disable-pan.patch`.
   Fixed by `0128-pra-disable-pan.patch` (value 0). Consumers checked:
   `osfmk/arm/arm_init.c:527/686`, `osfmk/arm64/copyio.c:88/98`,
   `osfmk/arm/pmap/pmap.c:13854/13873`.

2. **Framebuffer map size.** `mkadt_pra.py` declared `pra-fbcon`
   `reg = 0x5D000000 + 0x3000000` (48 MiB). `fbcon_probe()` calls
   `ml_io_map_wcomb(reg[0], reg[1])`; before `STARTUP_SUB_KMEM`, `io_map()`
   advances `virtual_space_start` by that size, while `arm_vm_init()`
   pre-allocates L3 tables only for `Video.v_height * v_rowBytes` (~8.29 MiB).
   The 48 MiB mapping would walk past the reserved page tables. The donor
   declares exactly `1080 * 1920 * 4`; PRA now does the same (`0x7E9000`).
   ADT regenerated, still 9,680 bytes.

3. **Driver audit (all clear for first boot).**
   - `a5xelte_emmc.c`: `a5xelte_emmc_probe` has no caller; `emmcroot`,
     `emmcwrite`, `a5log` are boot args.
   - `a5xelte_keys.c` / `a5xelte_touch.c`: `a5xelte_touch_probe` has no
     caller; keys/touch are boot-arg gated, and 0127 sets
     `A5_KEYS_DEFAULT`/`A5_TOUCH_DEFAULT` to 0.
   - `sweet_ufs.c`: `sweet_ufs_init` is only reachable from
     `sweet_ufs_rootdev`, inside the SWEET-only block.
   - `sweet_sample.c`: boot-arg gated (`sweetsample`).
   - `sweet_keys.c` / `sweet_touch.c` are `ARM64_BOARD_CONFIG_SWEET`-only, so
     they are not compiled for PRA; the calls in `sweet_ufs.c` sit in the
     SWEET-only block too.
   - `pe_serial.c` klog is DREAMLTE-only, so PRA never maps `A5_KLOG_PHYS`.

4. **DREAMLTE branch risk.** `A5XELTE.h` hardcodes `#define DREAMLTE 1`, so
   the donor's current tree only builds the DREAMLTE branch. PRA (no DREAMLTE)
   takes the `#else` branches, which the donor has not built recently. Checked
   the boot-critical ones: `arm_vm_init.c:1908/1916/2320` fall back to the
   generic physmap slide and the Video-based VA reservation; `pe_serial.c`
   klog is skipped. The remaining `#else` branches are in the disabled
   key/touch drivers. Watch this on the first CI run.

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

## Button-free mode switching (proven 2026-11-09)

The `fastboot` partition (`mmcblk0p5`) is a raw ARM64 bootloader image with an
embedded symbol table. Its misc parser (`check_misc_info`,
`comm_read_misc_cmd`) accepts `boot-recovery`, `boot-erecovery` and
`boot-safemode`.

Empirically confirmed on the device:

- Writing ASCII `boot-recovery` at **offset 0** of `misc` (`mmcblk0p20`) and
  issuing a normal `adb reboot` boots **TWRP**, not Android.
- The bootloader **clears the command after reading it** (one-shot BCB): after
  the recovery boot, `misc` was already all zeros.
- `misc` is restored to zeros; the phone is back in Android.

Exact test (from TWRP root, where the block device is writable):

```
printf "boot-recovery" | dd of=/dev/block/bootdevice/by-name/misc bs=1 count=13
sync
adb reboot
```

This removes the need for the power+volume button combo (which is awkward
because of the unlocked-bootloader warning screen).

## Shim run 2026-11-09 (p30 route, display + eMMC confirmed)

- `fastboot flash kernel` (p30) is allowed; `misc` and `erecovery_kernel` are
  rejected with "Command not allowed". The shim can therefore run from the
  normal kernel partition.
- The UART clock is gated at handoff: `FR` reads all-ones, so the old
  `uart_wait()` spun 1e6 iterations per character before reaching the
  framebuffer. UART output is now disabled in `console.c`; the screen is the
  only output we can observe.
- The old shim gated on Present State bit 16, which is **Buffer Read Enable**,
  not card-present. Both `sdhci_read` and `sdhci_write` returned -1 before
  touching the card. Fixed: no bit-16 gate, normal status low 16 / error status
  high 16, bounded busy waits, and a read-back verify of the written sector.
- Early-flood test: the shim floods `0x5D000000..0x60000000` red and
  `0x31000000..0x32A40000` blue as its first action. The screen turned **red**,
  proving (a) the shim executes from p30, and (b) the bootloader splash
  scanout base is the **logo buffer `0x5D000000`**, not the graphic carveout.
- The shim then wrote `misc=boot-recovery`, read it back, wrote the 25-sector
  `PRADMP01` dump to `erecovery_kernel + 16 MiB`, and reset via PSCI. The phone
  rebooted every ~10-15 s: recovery shares the `kernel` partition, so with
  p30 = shim, `boot-recovery` runs the shim again. This proves the misc write,
  read-back and PSCI `SYSTEM_RESET` all work.
- Next: restore stock p30, boot TWRP with the volume combo, read
  `/dev/block/mmcblk0p27` at LBA 786432 (25 sectors), and parse with
  `tools/pra_parse_dump.py`.

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
  offsets `0x82B1000/0x82B2000`, DRAM `0x88000000+0x20000000`, timebase
  1.92 MHz, 8 CPUs, `pra-fbcon`, `pra-emmc`). Produces a 9,680-byte ADT.
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

## Stage B: the XNU handoff is proven on hardware (2026-11-10)

The PRA loader now exists and has run on the device. It is the donor's
`SWEETXNU` v1 format and `boot_args` layout, with three PRA-specific
decisions:

1. **XNU window `0x88000000..0xA8000000` (512 MiB), not `0x80000000`.**
   `/proc/iomem` has a 32 KiB hole at `0x87b00000..0x87b07fff`, and
   `boot_args` carries one contiguous `physBase`/`memSize` pair, so the
   hole must stay outside the window. `0x88000000` is 2 MiB aligned and
   contiguous to `0xa8000000`; the ADT's `dram-base`/`dram-size` now match,
   and `mkpayload` reads the window from the ADT, so loader and kernel
   cannot disagree.

2. **The payload is embedded at `0x500000`, not read from the initrd.**
   `fastboot` only allows `kernel`/`ramdisk`/`recovery_ramdisk`, and the
   stock `kernel` image has no ramdisk, so depending on the bootloader to
   publish `linux,initrd-start` would be an untested assumption. The build
   pads the loader to `0x500000`, appends the payload, and sets the arm64
   header's `image_size` so the bootloader's `add_device_tree()` places the
   DTB after the payload. `__payload_start` is an absolute link-time
   constant; the exact payload length is patched into
   `pra_payload_size` in the loader image, so bounds checks do not depend
   on the DTB address.

3. **Console is the framebuffer, not UART.** `boot_main.c` attaches the
   `0x5D000000` splash buffer and prints each step. This is the first code
   in the port to draw glyphs (the diagnostic shim only filled solid
   colours); the console path and font work.

New files:

- `shim/pra/boot_main.c` — `pra_main()` for the loader build: validate the
  payload, copy segments, zero `.bss`, clean caches, place the ADT and
  `boot_args`, print the addresses, jump.
- `shim/pra/xnu_jump.S` — `pra_jump_mmu_off()`: DAIF mask, clear
  `SCTLR_EL1.M/.C/.I`, `br` to the entry with `x0 = boot_args`.
- `shim/pra/xnu_boot.ld` — links at `0x480000`, `__payload_start = 0x500000`.
- `shim/pra/test_payload.c`, `test_payload.ld` — a no-`.bss` stub linked at
  `0x88000000` that paints a green band and draws `boot_args->physBase`
  and `->memSize` as 32 bit bars (white = 1).
- `shim/pra/build-xnu.sh` — builds loader + ADT + test payload and packages
  `outxnu/pra-xnu.img`.
- `tools/mkpayload_flat.py` — `SWEETXNU` v1 packer for a flat binary, same
  header as `mkpayload.py`.

**Hardware result.** Flashed `outxnu/pra-xnu.img` (10,240 bytes) to
`kernel` (p30) with `fastboot flash kernel`, rebooted. The screen showed
`PRA XNU loader`, the addresses, `jumping to XNU`, then a green band and
the bit bars. The bars form a "Y": `physBase 0x88000000` lights bits 31
and 27 (two top bars) and `memSize 0x20000000` lights bit 29 (one bottom
bar between them). That is the ADT's window, read back from `boot_args` by
the payload at `0x88000000` — the full EL1 loader → segment copy →
`boot_args` → MMU-off jump path works.

Device is now halted in the stub. Restore: `fastboot flash kernel` from
`/mnt/giochi/pra-lx1-handoff/dump/mmcblk0p30.bin`.

## Stage B: CI build of the real XNU kernel (2026-11-10)

The `xnu` workflow runs on `macos-15` (the only arm64 runner this account can
start) with Xcode 16.0, the macOS 15 SDK and KDK 13.5 auto-downloaded from the
dortania manifest. Builds are dispatched, not pushed:

```sh
RUNNER=macos-15 tools/pra_ci.sh Kamion008/ios-pra
```

First real build (run 42845100412) reached the very end of the kernel compile
(4m27s) and failed only on two PRA port bugs; iig, mig, ctfconvert and the
`0083` iig patch all worked under Xcode 16, so no Xcode 15 pin or older SDK is
needed:

- `iokit/Kernel/arm/SweetCPU.cpp` uses `A5_BOOT_MPIDR`, which only
  `A5XELTE.h` defines. PRA does not include that header (it would pull in the
  Exynos framebuffer), so `PRA.h` now defines it as 0, matching the ADT's
  logical CPU 0 `reg = 0x000` (Kirin 655 boots on cluster 0/core 0).
- `osfmk/arm/commpage/commpage_asm.s` picks its lock sequence with
  `#if defined(ARM64_BOARD_CONFIG_A5XELTE)`. Assembly does not see
  `board_config.h`, so PRA compiled `casa`, which needs ARMv8.1 LSE. The guard
  now also accepts `ARM64_BOARD_CONFIG_PRA`, selecting the `ldaxr`/`stxr`
  Cortex-A53 path.

Both fixes are `xnu/patches/0129-pra-a5-boot-mpidr-and-armv8-commpage.patch`
and verified to apply to the exact patched tree from the failed run.

The second build (run 42848656649) compiled the whole kernel and reached the
final link, then failed with 14 undefined symbols in two families: the
`a5xelte_*` / `sweet_*` driver hooks and BearSSL `br_sha384/512_*`. Both have
the same cause: 23 sources gate their entire body on
`#if defined(ARM64_BOARD_CONFIG_A5XELTE)` before including any header, and
PRA only defined that macro inside `PRA.h`. Those files compiled to empty
objects, so `sweet_sha2big.o` (the BearSSL SHA-512 implementation) and the
eMMC/key/touch/AMFI/UFS drivers exported nothing.

`xnu/patches/0130-pra-define-a5xelte-at-compile-time.patch` passes
`-DARM64_BOARD_CONFIG_A5XELTE` in `MACHINE_FLAGS_ARM64_PRA` and guards the
`A5XELTE.h` include in `board_config.h` with `!defined(ARM64_BOARD_CONFIG_PRA)`,
so PRA gets the macro in every translation unit without inheriting
`A5XELTE.h`'s hardcoded `DREAMLTE` / Exynos 8895 addresses.

The eMMC probe is still opt-in (`emmcprobe=1`), keys and touch keep their
`A5_*_DEFAULT 0`, and `rd=md0` never reaches the eMMC/UFS root paths, so the
Exynos drivers are linked but inert on the first PRA boot.

The third build (run 42851091532) then came down to a single undefined
symbol, `_dreamlte_battery_read` from `SweetBattery::poll()`. That function
lives in the `#if defined(DREAMLTE)` half of `bsd/dev/a5xelte_touch.c`
(MAX77865 gauge), and PRA correctly does not define `DREAMLTE`.
`0131-pra-battery-no-dreamlte-gauge.patch` adds a PRA-only inline stub that
returns failure, so `poll()` publishes the static fallback instead of probing
Exynos I2C; the S8 build still links the real gauge.

The full log was unreadable through `gh run view --log` (HTTP/2 reset); see
`docs/pra-ci-access.md` for the `curl --http1.1` job-log workaround.

## First real kernel boots on hardware

Build 4 (run 42852547344) produced a 17 MB arm64 Mach-O kernel; the single
reported "LSE" hit is a false positive (`K256`, the SHA-256 constant table,
misdisassembled as `ldumaxah`). Packaged to a 5,980,160-byte boot image and
flashed to p30.

Boot 1 proved loader -> XNU -> framebuffer console on the phone, then panicked
at `pe_init.c:314` (`*delta >= 0`). The macOS-target build defaults
`show_progress = TRUE`, and `PE_state.video` comes from `boot_args->Video`,
which the shim leaves zero, so `display_size / 2 == 0`. Repackaged with
`-noprogress`; no kernel change needed.

Boot 2 got through `zone_init` and panicked in `IOPanicPlatform::start`:

    panic(cpu 0 caller ...): Unable to find driver for this platform:
      "hisilicon,hi6250".   IOPlatformExpert.cpp:2330

The kernel config table's `SweetPlatformExpert` entry only matches
`samsung,a5xelte` / `samsung,dreamlte`, so the catch-all panic driver won the
match. `0132-pra-platform-expert-name-match.patch` adds `hisilicon,hi6250` to
the PRA `IONameMatch` list; the A5XELTE/S8 lists are unchanged.

With no `rd=` argument, `IOFindBSDRoot` matches `IOMedia`/`Apple_HFS`, times
out after `ROOTDEVICETIMEOUT`, prints `Still waiting for root device`, and the
macOS-target branch calls `IOSetRecoveryBoot(..., reboot=true)`. There is no
`PE_halt_restart` implementor on PRA, so that returns instead of resetting and
the kernel repeats the wait. That is the expected landing point for the next
boot: platform expert -> CPU -> BSD init -> root wait.

## Boot 3: platform expert, stale image, preempt panic (2026-11-11)

The image flashed on 2026-11-10 evening was not built from `0132`: its
embedded match table carried only `hisilicon,hi6250-display` (the display
probe name), so it reproduced boot 2's platform-expert panic. The reliable
check is the match string inside the payload, not the file mtime:
`out/ci/kernel.development.pra` contains `IONameMatch` ->
`hisilicon,hi6250`, the flashed payload did not.

Repackaged from that verified artifact (`tools/pra_package.sh
out/ci/kernel.development.pra`) to 5,980,160 bytes, sha256
`3c30d7f6e830a1d432469153f8bd9864a999ce9cbad5168b2001d15687a429c7`, cmdline
`debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress`, and flashed to p30. The
packager now prints the flash command with `$PRA_SERIAL` instead of a literal
device serial; export it in the shell that flashes.

Boot 3 (photo, 2026-11-11 ~10:48) reached the intended landing point:

    A5XELTE: platform expert registered
    A5XELTE: CPU 1/1 init, SGI1 verified
    AMFI ... permissive sandbox
    A5XELTE MFS: hfs=527.100.6 registered, meminit 164 MB
    dill_init
    ifnet_attach lo0 / gif0 / stf0
    IOFindBSDRoot: Waiting on <dict ... Apple_HFS ...>

With no `rd=` and no media registered, that is exactly where the kernel is
expected to sit: platform expert -> CPU -> BSD init -> root wait.

The same screen then shows a panic:

    panic(cpu 0 caller 0xfffffff007420a1c): preemption count not 0 on thread
      0xffffffe63b9f4380 (1)
    Original panic string:
    handshake structure not initialized
    Please go to https://panic.apple.com to report this panic

The caller address is the format-string address of
`L_preempt_count_notzero_str` in `osfmk/arm64/locore.s` (file offset
`0x41ca1c` + kernel base `0xfffffff007004000`), so the site is the
`MACH_ASSERT` check at `return_to_user`/`check_user_asts` and the KASLR slide
is 0. `Original panic string:` is empty and the KDP handshake line follows
because `debug=0xc` leaves DB_NMI set: `panic_spin_forever()` keeps the CPU
and the Huawei bootloader watchdog eventually resets the phone, which is the
reboot cycle seen on screen.

What is observed but not explained: no root device exists at this point, and
`IOFindBSDRoot` loops in `waitForService` until a match appears, so
`bsd_init` should not have reached `bsd_utaskbootstrap` and no first user
thread should exist. Yet a thread is at `return_to_user` with preempt count
1. Either the wait path leaks the count (a preemption disable not balanced
across `thread_block`/`IOSleep`), or the thread is not the thread we expect.
Guessing is not useful here; instrument the assert next.

### 0133: the check fires, then a self-inflicted console panic

Run 43014519898 built 0133 (`sha256 b9c57205…`; the LSE scan again reports
only the `K256` false positive). The `PRA-PREEMPT` strings are in the payload,
and the packaged image (5,980,160 bytes, `sha256 9d62464a…`) kept the usual
cmdline.

The next boot produced a *different* panic:

    panic(cpu 0 caller 0xfffffff007aaa418): Console I/O from interrupt-disabled
      context @serial_console.c:168

That is a bug in the instrumentation, not in the kernel: the helper disabled
interrupts before printing, and `console_io_allowed()` in
`osfmk/console/serial_console.c` panics on exactly that in DEVELOPMENT. What
it does prove is that `preempt_count_notzero` is reached on every boot, so the
preemption assert is a real, repeatable entry point.

The guard is a tunable (`nointr_consio`), so the follow-up needed no rebuild:
the same 0133 kernel was repacked with
`debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress nointr_consio=1`, flashed
and rebooted. The next `PRA-PREEMPT:` line is the data we want.

Boot 4 also matters for the hypothesis: its log ends at `ifnet_attach ... lo0
... Proceeding.` and panics there, slightly *before* boot 3's photo, which had
already printed the `Apple_HFS` wait line. The assert is therefore not tied to
the root wait itself, which weakens the "wait path leaks preemption" idea.

### The second failure: ast_taken_user on an idle thread

With `nointr_consio=1` the console guard stays quiet, but the boot still dies,
now here:

    panic(cpu 0 caller 0xfffffff007a7be80): ast.c:166 Assertion failed:
      (thread->state & TH_IDLE) == 0

`ast.c:166` is inside `ast_taken_user()`, the return-to-user AST path, and the
assert is exactly "the thread being resumed to EL0 must not be the idle
thread". So the two panics are one story: a thread the scheduler believes is
`TH_IDLE` is being returned to user mode; the preemption assert was just the
first guard to notice. That also weakens any "the root wait leaks a preemption
count" theory: the thread identity, not the wait, is wrong.

The `PRA-PREEMPT` `printf` itself still never appeared on the framebuffer, even
with the tunable set, so the print path cannot be trusted from that context.
Panic strings always print (the panic path sets `console_suspended`, which
bypasses `console_io_allowed()`), so 0134 moves the data into the panic
strings: `PRA-PREEMPT cnt=… thread=… current=… idle=… task=… pid=… state=…
saved_pc=… saved_cpsr=… lr=… fp=… ELR_EL1=… SPSR_EL1=…`, and a matching
`PRA-ASTIDLE` panic in `ast_taken_user()` for the branch that hits the assert.

Photo pacing note: the framebuffer console is append-only and the screen keeps
the previous boot's tail above the new log, so a photo can show one panic from
the previous boot plus the current boot still running. Read the panic line's
address and the boot banner, not the position on the glass.

0134 (run 43018834356, `sha256 5b8127da…`, image `sha256 7929ab40…`) contains
both strings and was flashed with the canonical cmdline. Local compile replay
now works off the CI artifact: `tools/xnu-cc.py` takes `XNU_CC_CLANG` and
`XNU_CC_DXB`, so `/usr/bin/clang` plus `/tmp/pra-buildtree` reproduce the CI
flags without a macOS run (`SweetBattery.cpp`: 0 failures). That is what makes
a delegated driver patch compile-checkable here.

### 0134 data: the idle thread pointer, but not the idle state bit

The panic string came back on the first 0134 boot:

    PRA-PREEMPT cnt=1 thread=0xfffffff33b8d0430 current=0xfffffff33b8d0430
      idle=0xfffffff33b8d0430 task=0xfffffff33b8b49a8 pid=0 state=0x04
      saved_pc=0xf4f01ad3 saved_cpsr=0x7b39460 lr=0xfffffff007415d44
      fp=0xfffffff94a305ff0 ELR_EL1=0xfffffff007415d5c SPSR_EL1=0x000000384

Correction to an earlier reading: `0x04` is **`TH_RUN`**, not `TH_IDLE`
(`TH_IDLE` is `0x80`, `thread.h:421`, and it is set once in
`idle_thread_create` and never cleared except by a whole-state assignment).
So at this point `current_thread() == processor->idle_thread` by pointer, but
the state word does not carry `TH_IDLE`. The panic happens after the
`if_attach`/dlil phase of `bsd_init` (the last screen line is dlil's
"scheduled at least once. Proceeding."), i.e. the bootstrap thread blocks
there and the CPU idles.

The register pair is internally inconsistent in an informative way: `lr` and
`ELR_EL1` both land inside `_pmap_remove_pv` (+0x124 / +0x13c), and
`SPSR_EL1 = 0x384` has `M = 0b0100` (`EL1t`), so the most recent exception
came from **kernel** mode in pmap code; `fp = 0xfffffff94a305ff0` is a kernel
stack address. But the saved state the check read (`saved_pc`/`saved_cpsr`,
from `[x21]`, `x21` being the exception frame or `machine.contextData`) says
EL0 (`M = 0`, user `0x7b39460`). A user-looking saved state against a
kernel-mode exception is either a frame from an older exception on the same
stack, or an idle thread whose `machine.contextData` is not what a kernel
thread should have. `bt` frames in 0136 are meant to pick which.

`cnt=1` at this site is not automatically a leak: `BEGIN_INTERRUPT_HANDLER`
in `locore.s` adds 1 for the duration of an IRQ handler and
`END_INTERRUPT_HANDLER` removes it, and the idle thread adds one permanently
in `idle_thread()`. The question is why this check sees the count at all,
which only happens when the saved CPSR selects EL0.

0136 (run 43023175727, kernel `sha256 3eecefc8…`, image `sha256 ae872358…`)
adds the guarded frame-chain walk (`bt=%p,%p,%p,%p,%p`) to the same panic
string and is on the phone. Its photo:

    PRA-PREEMPT cnt=1 thread=0xfffffff39fdaa820 current=0xfffffff39fdaa820
      idle=0xfffffff39fdaa820 task=0xfffffff36ca04080 pid=0 state=0x04
      saved_pc=0xf4f02e97 saved_cpsr=0x7b39460 lr=0xfffffff007415d44
      fp=0xfffffffbfbd3af0 ELR_EL1=0xfffffff007415d5c SPSR_EL1=0x000000384
      bt=0xfffffff00742084c,0,0,0,0 @machine_routines.c:2922

`bt[0]` is `return_to_user+0x3c`, i.e. the helper's own return address; the
walk stops because the next `fp` is the interrupted context's frame pointer,
not a call chain. So 0136 did not answer the path question.

Two things the 0136 data settles:

- The panic is at the root wait itself: the last pre-panic line is
  `Waiting on <dict ... Apple_HFS ...>`, not the dlil phase (dlil lines are
  from the *previous* boot on the append-only framebuffer).
- `lr`/`ELR_EL1`/`SPSR_EL1` are bit-identical to 0134, so the last kernel
  exception in every boot is the same instruction with the same PSTATE.
  `lr` is the interrupted context's LR (POP_FRAME restores it), so the
  exception that matters was taken from **kernel** mode.

  Careful: the digits in this log do not agree with each other. As written,
  `0xfffffff007415d5c` is `cpu_idle+0x1ec` — the instruction *after* the
  `wfi` in `cpu_idle` — and `0xfffffff007415d44` is `cpu_idle+0x1d4`, the
  return address after the `platform_cache_idle_enter` call. That reads
  naturally: the timer/FIQ that wakes the idle WFI is taken exactly at the
  first instruction after `wfi`. `0xfffffff007411d5c` would instead be
  `pmap_remove_pv+0x13c`, which is what an earlier reading of these same
  photos recorded. The two candidates differ only in one hex digit
  (`7411` vs `7415`), and the low half (`…d44`/`…d5c`, 0x18 apart) is the
  same either way. The idle thread cannot execute `pmap_remove_pv`, so the
  `cpu_idle` reading is the one that fits `thread == current == idle`; treat
  `pmap_remove_pv` as unverified until the next photo re-reads these fields.

  `SPSR_EL1 = 0x384` is `EL1t` with `D|A|I` masked and `F` unmasked. `D` is
  set automatically on exception entry and XNU never masks it outside the
  `DAIFSC_ALL` sites (return-to-user/kernel, `start.s`), so a `D=1`
  interrupted state means the exception was taken **inside an exception
  handler**, not on a plain kernel thread stack. That is consistent with the
  preempt count: `BEGIN_INTERRUPT_HANDLER` adds one for the duration of an
  IRQ/FIQ handler, so a nested exception inside a handler finds the count
  already at 1.

That leaves `saved_pc`/`saved_cpsr` (read from `[x21]`, the value the dispatch
used to choose user vs kernel return) as the only corrupt-looking pair:
`0x7b39460` has reserved SPSR bits set and no valid mode encoding, and
`0xf4f02e97` is below the 4 GiB user base. Both differ per boot in the low
bits while `0x7b39460` repeats exactly, which is stale stack data, not a
saved user context. So the likely shape is: `exception_return_dispatch` read
a CPSR that is not the current frame's, saw `M == 0`, and sent a kernel
exception return down the user path.

0137 passes `x21` itself to the helper and prints `tid`, `continuation`,
`machine.contextData`, `machine.upcb`, the per-CPU `cpu_active_thread` and
`cpu_int_state` (the frame pointer the IRQ prologue stored), plus ESR/FAR.
If `x21 == cpu_int_state`, the frame pointer is intact and the frame contents
are wrong; if not, `x21` was clobbered before the dispatch.

## 0138: idle stack fix and frame probes (2026-11-11)

The 0137 photo and disassembly establish that `Idle_context` parked
`cpu_idle()` on the interrupt stack at `intstack_top - 0x50`, while an EL1 SP0
exception saved its frame below that stack pointer and the handler then
switched back to `intstack_top`. The handler frame therefore overwrote both
the idle call frame and the exception frame, including the saved PC/CPSR used
by exception dispatch.

0138 keeps the PRA idle thread on its kernel stack instead of switching
`Idle_context` to `CPU_ISTACKPTR`. It also records DAIF at `cpu_idle()` entry
and just before WFI, records SP before WFI, and adds the current SP/DAIF,
interrupt/exception/kernel stack pointers, frame consistency, and idle probes
to the panic string. This addresses the observed stack overlap and gives the
next photo enough data to resolve why the saved exception state reported
`SPSR_EL1.F == 0`.

The patch is committed as outer-repository commit `2101ff9`. The matching
working-tree edits remain in `xnu-src/` for compile replay. No 0138 build or
hardware result is available yet: the prior `/tmp` compile log/buildtree are
absent in this environment, and CI dispatch stopped before pushing because
the GitHub CLI has no OAuth token. The existing `out/ci` kernel is the 0137
artifact and is not evidence for 0138. No phone flash was attempted.

The 0135 hi6250 pinctrl driver draft is at `/tmp/0135-pra-hi6250-pinctrl.patch.draft`,
outside the active `xnu/patches/` directory because CI applies every patch
there. It adds `PRAPinctrl.cpp` and a PRA-only IOKit match entry; the build-list
entry remains absent. `git apply --check` passes against the local XNU HEAD,
but it is uncompiled because the compile log and generated buildtree are not
available in this environment. It is a draft, not ready to activate.

## Future GPU reference

The user pointed to [Nik300/viva-gpu](https://github.com/Nik300/viva-gpu) as
a useful later reference. Its README describes an iOS 16.7.16 Metal stack
using Mesa/Panfrost and AIR-to-NIR translation for Mali-G57, with userspace
and mock testing in place while the XNU accelerator driver remains future
work (README status dated 2026-11-03). The PRA kernel config identifies the
hi6250 GPU as Midgard (`live/kernel-config.txt`); this suggests the project
will be useful as a design reference for the userspace/IOKit boundary, while
its G57 backend should not be treated as a drop-in for this different GPU
family. This is separate from the current root-device boot blocker.

## Next actions
1. Restore GitHub CLI authentication or connect the GitHub integration, then
   dispatch the PRA build for commit `2101ff9`. Replay the three changed XNU
   files against the downloaded buildtree and record build success separately
   from any device observation.
2. If the build passes, package and directly flash only the authorized kernel
   image while preserving bootloaders, recovery, modem, and persist. Then run
   `tools/notify.sh` and request a photo from the phone owner. Record the
   screen and runtime behavior as separate claims from the build result.
3. Review the next photo's 0138 panic fields. If it still panics, use
   `frame_ok`, DAIF, stack pointers, and the idle probes to choose the next
   fix; if it clears the panic, record the exact root-wait or later boot state.
4. Review the 0135 draft against `docs/pra-driver-contract.md`, integrate its
   device-tree nodes in `tools/mkadt_pra.py`, and have the primary build and
   boot that reviewed patch.
5. Keep device serials and dumps out of git and retain the optional kexec
   route only as a faster iteration path.

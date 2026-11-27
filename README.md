# iOS on the Huawei PRA-LX1

**XNU (iOS 16 generation) and the unmodified iPhone X iOS 16.7.16 userland, on
the Huawei PRA-LX1 (hi6250 / Kirin 655, 1080×1920).**

This repo ports Apple's open-source XNU kernel (xnu-8796, the iOS 16
generation) to the Kirin 655 and boots the **unmodified iPhone X iOS 16.7.16
(20H392) userland** on top of it: launchd, the system daemons, backboardd,
SpringBoard. Donor tree: [ios-galaxy-s8](https://github.com/Kamion008/ios-galaxy-s8)
(Samsung S8 / SWEET, which reached the iOS home screen).

> ⚠️ Experimental bring-up, not a usable phone OS. Installing it **erases the
> userdata partition** (all Android data). Only PRA-LX1 (hi6250). Kernel and
> logs only write to the `erecovery_kernel` partition (p27); bootloaders,
> recovery, modem, persist and EFS are never touched.

## Status (2026-11-23)

| Area | State |
| --- | --- |
| Boot | Stock Huawei bootloader → LK failsafe loads p27 → our boot image (ADT + payload + cmdline) → XNU; **~6 minutes power-to-lock-screen** (T22, known-good) |
| CPU | 4× Cortex-A53 (ARMv8.0, no LSE, no PAN), GIC-400, armv8 timer; 8-core cluster-1 boot = expected sched_lock panic (diagnostic, patch 0204 instruments it) |
| Storage | Own Arasan SDHCI eMMC driver (polled PIO). Journaled case-sensitive HFS+ iOS root in `userdata`, read/write; GPT-probed |
| Logs | 4 MiB console ring at the tail of `erecovery_kernel`, flushed every 10 s and on panic; pulled from TWRP |
| iOS userland | launchd → 100+ daemons exec; **the Setup wizard is bypassed** (purplebuddy prefs) and DataMigration is skipped |
| GUI | **The iOS 16.7.16 lock screen renders** (clock, unlock grabber) — CPU-only, no GPU; ~2 of the last 3 boots reach it |
| Touch | The CYTT21403 probe is read-only I2C; causality answered — **a wake event DOES re-enable the digitizer**, and backboardd believes the panel is awake because SpringBoard publishes an asserted sensor mode (score 4108, LockButton, WakeOnTapEnabled). The keyless-boot deliverable (no synthetic key) is the open step |
| Diagnostics | In-kernel per-thread sampler (`sweetsample=…`): user pc/bt + kernel-side state (thread pointer, wait state, wait event, wait queue, block caller, kernel fp chain) printed to the ring every 2 min |
| Crashes | Panic backtraces go to screen AND the eMMC ring; every kernel panic since 0156 was root-caused and fixed |

**Current blockers (named, in fix order):**

1. **1.375 GiB RAM change panics early VM init** — T24 (patch 0203 + RAM
   `0x40000000 → 0x58000000`, no `a5fb_keep_on`) panicked ~2 s after power-on:
   `kmem_range_init: vm_map_locate_space failing for claim compressor
   @ vm_kern.c:3645`. The RAM change alone (never boot-tested) is the prime
   suspect; the isolation flash (`out/pra-xnu-0202-1375mb.img`) is queued.
2. **`_pra_emmc_lock` wedge** — on some boots, launchd's `sync()` and a
   backboardd thread block uninterruptibly on the eMMC driver's own mutex
   (a lost wakeup / hold-across-sleep in the driver's lock discipline; the
   ring flusher keeps acquiring the same lock, which rules out a stuck
   holder). Fix: the driver lock audit → patch 0176.
3. **The wall clock is frozen** (the lock screen shows 4:08 forever):
   timers tick but `gettimeofday` does not advance — the
   timebase→wallclock conversion (ADT 1.92 MHz vs the real CNTFRQ).

**Touch status, in short:** patch 0202's advertised host-state lever
(MultitouchHostStateKeys) was **refuted by ring66** — ZERO host-state pushes
despite the advertisement. Patch 0203 (display-power honesty) is compiled
and CI-green but boot-tested only in the T24 combination that hit the RAM
panic. The 1×1-rect / events:0 / event-shape theories are refuted — do not
re-litigate them without new evidence. Hardware tracks: 8-core (patch 0204,
CI pending), RAM 1.375 GiB (the active blocker), GPU (G3D LPM3-IPC gate).

The active handoff with the full state, evidence and next steps:
[HANDOFF_2026-11-23e.md](HANDOFF_2026-11-23e.md). Run diary:
[PRA-LX1_PROGRESS.md](PRA-LX1_PROGRESS.md) and [PRA-LX1-noted.md](PRA-LX1-noted.md).

## The boot command line

The kernel's behavior is dictated by the boot command line. Every critical
argument has a reproduced failure mode when dropped (`cpus=1` hangs, missing
`pralog` loses all boot evidence, missing `wdt=-1` reboots the panic off the
screen). The proven string is the **default** of `tools/pra_package.sh`,
which refuses to package — and `tools/pra_flash_skip.sh` refuses to flash —
an image missing it. Do not weaken those gates; see the banner inside the
script. (`sweetsample` names the processes the in-kernel sampler dumps.)

## Build

GitHub Actions (`.github/workflows/xnu.yml`) builds on push touching
`xnu/patches/**` (macOS runner, Xcode 16, KDK 13.5 auto-downloaded). The
kernel artifact (`kernel.development.pra`) is packaged and flashed from a
Linux host:

```sh
tools/pra_package.sh /tmp/gh-art/kernel.development.pra   # cmdline is the default
PRA_SERIAL=<serial> tools/pra_flash_skip.sh shim/pra/outxnu/pra-xnu.img   # p27 + sha256 readback + reboot
PRA_SERIAL=<serial> sh tools/pra_readlog.sh               # pull the console ring from TWRP
```

The iOS root image is built by `sudo tools/pra-build-iosroot.sh` (applies
the donor root tweaks automatically) and staged with
`ADB="adb -s <serial>" tools/pra-stage-iosroot.sh <image> --yes`.

Device serials stay out of git: every tool takes `PRA_SERIAL` from the
environment. The repo contains only patches, docs and host tools — the XNU
source tree, device dumps and boot photos are gitignored.

## Repo layout

- `xnu/patches/` — the patch stack CI applies to xnu-8796 (0xx: donors,
  1xx: PRA bring-up; `0204` is current)
- `shim/pra/` — the loader (boot image assembly, ADT generator, payload)
- `tools/` — packaging, flashing, log pulling, root-image surgery and the
  donor root tweaks
- `work/` — per-session evidence: ring dumps, parsers, patch generators,
  milestone notes
- `HANDOFF_2026-11-23e.md` — the active handoff (start here)
- `PRA-LX1_PROGRESS.md` / `PRA-LX1-noted.md` — the run diary: every boot, its
  evidence and the next step
- `codemagic.yaml` + `tools/codemagic-port.md` — backup pipeline (manual only)

## Safety

The flasher writes **only** p27 (`erecovery_kernel`), verifies the sha256
readback before rebooting, and refuses a battery below 25% (the boot is
heavy CPU). Bootlogs persist on disk, so a hung boot is always recoverable
by power-cycling into TWRP.

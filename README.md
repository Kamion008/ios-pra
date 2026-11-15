# iOS on the Huawei PRA-LX1

**XNU (iOS 16 generation) and the unmodified iPhone X iOS 16.7.16 userland, on
the Huawei PRA-LX1 (hi6250 / Kirin 655, 1080×1920).**

This repo ports Apple's open-source XNU kernel (xnu-8796, the iOS 16
generation) to the Kirin 655 and boots the **unmodified iPhone X iOS 16.7.16
(20H392) userland** on top of it: launchd, the system daemons, backboardd,
SpringBoard and Setup. Donor tree: [ios-galaxy-s8](https://github.com/Kamion008/ios-galaxy-s8)
(Samsung S8 / SWEET, which reached the iOS lock screen).

> ⚠️ Experimental bring-up, not a usable phone OS. Installing it **erases the
> userdata partition** (all Android data). Only PRA-LX1 (hi6250). Kernel and
> logs only write to the `erecovery_kernel` partition (p27); bootloaders,
> recovery, modem, persist and EFS are never touched.

## Status (2026-11-15)

| Area | State |
| --- | --- |
| Boot | Stock Huawei bootloader → LK failsafe loads p27 → our boot image (ADT + payload + cmdline) → XNU |
| CPU | 4× Cortex-A53 (ARMv8.0, no LSE, no PAN), GIC-400, armv8 timer |
| Storage | Own Arasan SDHCI eMMC driver (polled PIO). HFS+ iOS root in `userdata`, read/write; GPT-probed |
| Logs | 4 MiB console ring at the tail of `erecovery_kernel`, flushed every 10 s and on panic (lock steal after a 5 s wait); pulled from TWRP |
| iOS userland | launchd → 100+ daemons exec; backboardd renders the Apple logo + progress bar and hands the display to the render server; SpringBoard alive for hours |
| GUI | Apple logo, progress bar, fade — **the Hello screen is the current blocker** |
| Crashes | Panic backtraces go to screen AND the eMMC ring (`PRA BT:` frames); every kernel panic since 0156 was root-caused and fixed |

**Current blocker:** Setup (`com.apple.purplebuddy`) hangs at scene creation
waiting for a synchronous XPC reply that never arrives; the launch watchdog
kills it (0x8badf00d). The in-kernel process sampler (`sweetsample=Setup`) now
dumps its threads every 2 minutes to name the missing peer. Detail:
[PRA-LX1-noted.md](PRA-LX1-noted.md) and [PRA-LX1_PROGRESS.md](PRA-LX1_PROGRESS.md).

## The boot command line

The kernel's behavior is dictated by the boot command line. Every critical
argument has a reproduced failure mode when dropped (`cpus=1` hangs, missing
`emmcmulti=0` gives card-busy mount errors, missing `pralog` loses all boot
evidence, missing `wdt=-1` reboots the panic off the screen). The proven
string is the **default** of `tools/pra_package.sh`, which refuses to package
— and `tools/pra_flash_skip.sh` refuses to flash — an image missing it. Do not
weaken those gates; see the banner inside the script.

## Build

GitHub Actions (`.github/workflows/xnu.yml`) builds on push touching
`xnu/patches/**` (macOS runner, Xcode 15.x is required — Xcode 16's `iig`
emits `IORPC.kernelContent`, which xnu-8796 lacks). The kernel artifact
(`kernel.development.pra`) is packaged and flashed from a Linux host:

```sh
tools/pra_package.sh /tmp/gh-art/kernel.development.pra   # cmdline is the default
PRA_SERIAL=<serial> tools/pra_flash_skip.sh shim/pra/outxnu/pra-xnu.img   # p27 + sha256 readback + reboot
PRA_SERIAL=<serial> sh tools/pra_readlog.sh               # pull the console ring from TWRP
```

Device serials stay out of git: every tool takes `PRA_SERIAL` from the
environment. The repo contains only patches, docs and host tools — the XNU
source tree, device dumps and boot photos are gitignored.

## Repo layout

- `xnu/patches/` — the patch stack CI applies to xnu-8796 (0xx: donors,
  1xx: PRA bring-up; `0161` is current)
- `shim/pra/` — the loader (boot image assembly, ADT generator, payload)
- `tools/` — packaging, flashing, log pulling, root-image surgery
- `PRA-LX1_PROGRESS.md` / `PRA-LX1-noted.md` — the run diary: every boot, its
  evidence and the next step
- `codemagic.yaml` + `tools/codemagic-port.md` — backup pipeline (manual only)

## Safety

The flasher writes **only** p27 (`erecovery_kernel`), verifies the sha256
readback before rebooting, and refuses a battery below 40% (the boot is an
hour of full CPU). Bootlogs persist on disk, so a hung boot is always
recoverable by power-cycling into TWRP.

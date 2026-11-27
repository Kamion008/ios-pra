# iOS on the Huawei PRA-LX1

**XNU (iOS 16 generation) and the unmodified iPhone X iOS 16.7.16 userland, on
the Huawei PRA-LX1 (hi6250 / Kirin 655, 1080×1920).**

This repo ports Apple's open-source XNU kernel (xnu-8796, the iOS 16
generation) to the Kirin 655 and boots the **unmodified iPhone X iOS 16.7.16
(20H392) userland** on top of it: launchd, the system daemons, backboardd,
SpringBoard. Donor tree: [ios-galaxy-s8](https://github.com/Floppikrob/ios-galaxy-s8)
(Samsung S8 / SWEET, which reached the iOS home screen; itself based on
[ios-sweet](https://github.com/dipa-studio/ios-sweet)).

> ⚠️ Experimental bring-up, not a usable phone OS. Installing it **erases the
> userdata partition** (all Android data). Only PRA-LX1 (hi6250). Kernel and
> logs only write to the `erecovery_kernel` partition (p27); bootloaders,
> recovery, modem, persist and EFS are never touched.

## Status (2026-11-23)

| Area | State |
| --- | --- |
| Boot | Stock Huawei bootloader → LK failsafe loads p27 → our boot image (ADT + payload + cmdline) → XNU. **~6–15 min to the lock screen** (the 0176/0177 eMMC-lock fix landed; the pre-0176 "wedge" that hung some boots on `_pra_emmc_lock` is root-caused and fixed) |
| CPU | 4× Cortex-A53 (ARMv8.0, no LSE, no PAN), GIC-400, armv8 timer. The port is already 8-core capable in source/ADT/config (a cmdline-only change), but `cpus=8` panics on a recursive `pset0.sched_lock` ticket-lock while registering cluster 1 — patch 0204 instruments that panic for the diagnostic |
| Storage | Own Arasan SDHCI eMMC driver (polled PIO). Journaled case-sensitive HFS+ iOS root in `userdata`, read/write; GPT-probed. The 0176 per-sector locking closed the boot-wedge blocker |
| Logs | 4 MiB console ring at the tail of `erecovery_kernel`, flushed every 10 s and on panic; pulled from TWRP |
| iOS userland | launchd → 100+ daemons exec; the Setup wizard is bypassed (purplebuddy prefs) and DataMigration is skipped |
| GUI | **The iOS 16.7.16 lock screen renders** (clock, unlock grabber) — CPU-only, no GPU; the wall clock was confirmed advancing (the frozen-clock theory was refuted) |
| Touch | The CYTT21403 digitizer is fully driven from the kernel: I2C bring-up, app-mode, 10 ms input poll, HID events injected into a queue backboardd maps/arms/drains. **Causality answered — a wake event DOES re-enable the digitizer**: the idle timer's `displayState: off` sensor-mode latches the digitizer off, and backboardd believes the panel is awake only after a wake/power event. The deliverable (touch works from boot with **no synthetic key**) is the open step |
| Diagnostics | In-kernel per-thread sampler (`sweetsample=…`): user pc/bt + kernel-side state printed to the ring; queue telemetry (enq/drop/head/tail), powerreq/display-power traces |
| Crashes | Panic backtraces go to screen AND the eMMC ring; every kernel panic since 0156 was root-caused and fixed |

**Current blockers (named, in fix order):**

1. **1.375 GiB RAM change panics early VM init** — T24 (patch 0203 + RAM
   `0x40000000 → 0x58000000`, no `a5fb_keep_on`) panicked ~2 s after power-on:
   `kmem_range_init: vm_map_locate_space failing for claim compressor
   @ vm_kern.c:3645`. The phone's 3 GB is **not** one contiguous block (8 fragments,
   a 512 MiB gap at 0x60000000, a 32 KiB hole at 0x87b00000); 1.375 GiB is the
   largest contiguous window. The RAM change alone (never boot-tested) is the
   prime suspect; the isolation flash (`out/pra-xnu-0202-1375mb.img`) is queued.
2. **The touch deliverable is gated on a wake/display-state path** — a synthetic
   power key (0198/0199/0200) makes touch work, but a keyless boot does not yet.
   0202's host-state lever was **refuted by ring66** (ZERO host-state pushes
   despite the advertisement); 0203 (display-power honesty) is the next lever,
   compiled and CI-green but boot-tested only in the T24 combination that hit the
   RAM panic.
3. **8-core (cluster-1) scheduler panic** — `cpus=8` is cmdline-only but panics on
   `pset0.sched_lock`; patch 0204 instruments it. Expected to panic (diagnostic).

**Touch status, in short:** the kernel half is fully proven (descriptor valid,
app mode, ~10–27 reports/s, HID events injected and drained by backboardd at
9.2× the queue capacity with zero drops). The blocker is **above the kernel**:
backboardd drains the queue intact but its HIDEventSystem does not route
digitizer events to SpringBoard's gesture recognizers while the display is
believed off. The 1×1-rect / events:0 / event-shape theories are refuted — do
not re-litigate them without new evidence.

The active handoff with the full state, evidence and next steps:
[HANDOFF_2026-11-23e.md](HANDOFF_2026-11-23e.md). Run diary:
[PRA-LX1_PROGRESS.md](PRA-LX1_PROGRESS.md), [PRA-LX1-noted.md](PRA-LX1-noted.md)
and [work/boots.md](work/boots.md) (every boot T1→T24 with ring evidence).
Per-claim evidence: [work/claim-*.md](work/claim-0181.md). Hardware tracks:
[work/hw-3gb-design.md](work/hw-3gb-design.md), [work/hw-8core-design.md](work/hw-8core-design.md),
[work/hw-gpu-status.md](work/hw-gpu-status.md).

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

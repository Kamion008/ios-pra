# PRA-LX1 XNU Bring-up Handoff

Updated 2026-11-12. This handoff is for continuing the Huawei PRA-LX1 / hi6250 bring-up in another model or session.

## ⚠️⚠️⚠️ THE PRA BOOT COMMAND LINE — DO NOT SKIP, SHORTEN, OR "SIMPLIFY" ⚠️⚠️⚠️

Every PRA kernel flash MUST use this EXACT cmdline (the proven string of every boot
that reached the daemons). It is now the DEFAULT of `tools/pra_package.sh` (no CMDLINE
env needed), and both `tools/pra_package.sh` and `tools/pra_flash_skip.sh` REFUSE an
image missing any of the 12 critical args (flash-gate bypass for deliberate
experiments only: `PRA_ALLOW_ANY_CMDLINE=1`). Failure modes, all REPRODUCED on the
phone: `cpus=1` hangs the SMP boot; missing `emmcmulti=0` → "PRA eMMC: card busy,
skip read" → root mount error; missing `pralog=1 praloglba=794623` → no eMMC ring →
all boot evidence incl. panic backtraces lost; missing `wdt=-1` → watchdog reboots
the panic off the screen. Full arg-by-arg list: `PRA-LX1_PROGRESS.md` (top block)
and `AGENTS.md` (top block). Copy-paste verbatim:

```
debug=0xc serial=3 cpus=4 keepsyms=1 rd=sdhcroot0 emmcroot=userdata emmcprobe=1 emmcwrite=1 rootrw=1 unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 emmcstats=1 pralog=1 praloglba=794623 sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1 sweetfb_hz=1 sweetsample=Setup praexecskip=locationd,WirelessRadioManagerd,fairplayd.H2,bluetoothd,nanotimekitcompaniond,CommCenter
```

## Objective and operating constraints

- Boot the iOS 16.7.16 / iPhone X arm64 XNU build on a Huawei PRA-LX1 (Kirin 655 / hi6250), currently blocked around root-device discovery.
- Direct flashing is authorized. Flash only the `kernel` partition for these XNU trials; preserve bootloaders, recovery, modem, and persist.
- Keep CI build success, artifact verification, flashing, screen observations, and actual root mount/userspace behavior as separate claims.
- Photos are the console channel. No UART or USB log stream has been authorized yet. Run `tools/notify.sh long` whenever the user must physically handle the phone.
- Never commit the device serial or dumps. Pass the serial through the environment as `PRA_SERIAL` when needed.
- `xnu/patches/*.patch` is what CI applies. Changes under `xnu-src/` alone are not part of CI.

## Current state

### CI build and verifier

- Run [#17](https://github.com/Kamion008/ios-pra/actions/runs/43211905251) completed successfully. The Build, `Verify PRA preemption diagnostics are linked`, LSE check, and artifact upload steps all passed. The workflow default runner is `macos-15`; the run was push-triggered after the verifier fix.
- The immediately prior run #16 built and uploaded its artifact, but the linked-kernel verifier failed with `LLVM ERROR: IO failure on output stream: Broken pipe`. The command used `xcrun llvm-nm ... | grep -q ...` under `set -o pipefail`; `grep -q` exited early and closed LLVM's pipe. The verifier was fixed by letting `grep` consume the full stream. This failure was in the guard, not the compiler or a missing-symbol result.
- Run #15, [43097286698](https://github.com/Kamion008/ios-pra/actions/runs/43097286698), has sat queued since Nov 11 with no job. Cancellation from GitHub's web UI failed twice; it still appeared queued at last check. Do not confuse it with run #17.
- Local `gh auth status` reports the CLI token invalid. The connected GitHub app can read runs, fetch artifacts, and update repository files, but did not expose workflow dispatch/cancel actions. The browser UI was used for manual dispatch/cancel attempts. Remote note/workflow file commits were made with the GitHub integration.

### Run #17 artifact and package

- User downloaded the artifact ZIP to `/home/kamion008/Ai/xnu-kernel (2).zip`.
- ZIP SHA-256: `cc96708d23f4b0c33534572028ea7744647d5922c5fb0861cc226f186e23c08c`, matching the run #17 artifact digest.
- Extracted kernel at `/tmp/pra-run17/kernel.development.pra`; manifest verification passed. Kernel SHA-256: `8d76ee0eb1d60739e9767b9bd38bf2456161aa9e4a8af46899574c75d63d898b`. It contains the `PRA-PREEMPT` diagnostic string; CI's linked-kernel guard also passed.
- Packaged image: `shim/pra/outxnu/pra-xnu.img`, 5,980,160 bytes, SHA-256 `9addb712e1a924cf8c3e91e234a82b2d089b62f4bd2de829795692ca8a994171`.

### Hardware and latest photo

- The run #17 image was flashed to the `kernel` partition only. Fastboot reported `Sending` and `Writing` as `OKAY`; it emitted the known AVB-footer warning (`kernel partition size: 0`, image size 5,980,160). `fastboot reboot` returned `OKAY`.
- The latest photo is `/home/kamion008/Downloads/PXL_20261112_120801399.jpg`. It includes `Waiting on <dict ... IOMedia ... Apple_HFS ...>` and early interface/driver initialization text. No panic is visible in this photo. It does not prove a root mount or userspace boot. The log ordering may include retained display output, so keep the boot-order interpretation tentative.
- Earlier photo `/home/kamion008/Downloads/PXL_20261111_192201710.jpg` showed the old 0138 artifact panic after the Apple_HFS wait: `preemption count not 0 on thread ... (1)`.
- After the previous failed image, disassembly showed the reported caller `0xfffffff007420a1c` fell inside stock `preempt_count_notzero` and the image lacked `_pra_preempt_notzero`/`PRA-PREEMPT`; the source/buildtree did contain the patch. This mismatch motivated the clean object deletion and linked-kernel assertion. Run #17 now passes the assertion, but no local disassembly of this downloaded artifact has been recorded yet.

## Technical diagnosis and patch history

- Patch numbers: 0135 is reserved for the delegated PRA hi6250 pinctrl driver; 0136 and 0137 were earlier diagnostics; 0138 is the idle-stack fix plus probes.
- 0137 screen/runtime data established an interrupt-stack collision: the exception frame was built at `intstack_top - 0x3a0`; `cpu_idle` used a nearby address on the same interrupt stack. `SWITCH_TO_INT_STACK` then started the handler at `intstack_top`, overwriting the frame and exception state. A clobbered CPSR was read as invalid saved state and `return_to_user` reached the preemption panic.
- 0138 changes `Idle_context` for PRA to keep `sp` on the idle thread's kernel stack instead of switching to `CPU_ISTACKPTR`. It also records DAIF/SP at `cpu_idle` entry and before WFI, and prints frame validity and stack/probe data in the panic string. The issue that `SPSR_EL1.F` appeared unmasked despite no source-level unmask in `cpu_idle` remained unexplained; the probes were intended to clarify it.
- Relevant patch: `xnu/patches/0138-pra-idle-kstack.patch`. Earlier context and evidence are in `PRA-LX1_PROGRESS.md` and `PRA-LX1-noted.md`.

## 0135 pinctrl draft

- Contract: `docs/pra-driver-contract.md`. Local source currently exists at `xnu-src/iokit/Kernel/arm/PRAPinctrl.cpp`, with a PRA-only config-table entry in `xnu-src/iokit/KernelConfigTables.cpp`.
- Delegated review found the draft maps and publishes the four audited pinctrl windows read-only and validates `reg`; it made no edits. It must not write registers.
- No `files.arm64` build entry and no `xnu/patches/0135-pra-hi6250-pinctrl.patch` exist yet. The agent did not add them because contract-required compile replay could not run: `/tmp/xnu-43018834356.log` and `/tmp/pra-buildtree` are missing. Keep this driver unlinked until compile evidence exists.
- The contract says the agent may touch only the new driver, the specified config-table entry, and the `files.arm64` line after compile. The ADT `pinctrl` node in `tools/mkadt_pra.py` is owned by the primary agent; merge it only after the driver compiles.

## Next steps

1. Continue from the latest photo: wait for additional screen progress if the user can provide it, or ask for another photo using `tools/notify.sh` before any physical action. Determine whether the Apple_HFS wait persists and whether a panic appears; do not infer boot success from CI or flash success.
2. If the same root wait persists, investigate the root-device discovery/mount path and the missing device/storage support. Keep runtime claims grounded in photos.
3. Resume the 0135 driver only after restoring the compile log/buildtree or obtaining a usable CI buildtree artifact. Follow `docs/pra-driver-contract.md`; compile the new source before adding the build-list line or exporting the 0135 patch.
4. Before any later flash, verify the exact artifact and package hash again; flash only `kernel`, use `PRA_SERIAL` from local context, and preserve other partitions.
5. Keep `PRA-LX1-noted.md` current. Do not commit private serial values, dumps, or generated device captures.

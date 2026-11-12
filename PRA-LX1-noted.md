# PRA-LX1 bring-up notes

Updated 2026-11-12.

## 0138 CI and package

- GitHub Actions run [43082795820](https://github.com/Kamion008/ios-pra/actions/runs/43082795820) completed successfully for commit `103bfb8932f2947929ba4495fffc216c14c65a52`.
- The `xnu-kernel` artifact manifest reports SHA-256 `a821543680cf3665f772854af0866222c88fc519923e6525f24b0424c5f8850e` for the artifact archive.
- Extracted `kernel.development.pra` SHA-256: `909761192f9f45d320c54e1c8306ca90f1508c3045ddd6335df07de764a69408`.
- Packaged `shim/pra/outxnu/pra-xnu.img`: 5,980,160 bytes; SHA-256 `93599fee798eb0b36e68611b894570bc26f827519a5ba47a34bfc1e2c2b6af91`.

These establish CI build success and local packaging only. They do not establish that the image has been flashed or booted on the PRA-LX1.

## Follow-up CI verification

- Run [43094838455](https://github.com/Kamion008/ios-pra/actions/runs/43094838455) rebuilt from a clean object directory. The Build and LSE-check steps succeeded, but both artifact uploads failed. The linked-kernel guard was skipped because the earlier buildtree upload failure made its `success()` condition false; no kernel artifact was available from this run.
- Run [43097286698](https://github.com/Kamion008/ios-pra/actions/runs/43097286698) uses a workflow update that skips the large buildtree upload and makes the PRA guard run independently of optional artifact failures. As of 2026-11-12, GitHub reports the run queued with no job assigned. No kernel artifact or additional hardware flash is confirmed from this run.
- A cancellation attempt for run 43097286698 was rejected by GitHub twice with “Failed to cancel workflow.” Run [43210924043](https://github.com/Kamion008/ios-pra/actions/runs/43210924043) was manually started with runner `macos-15`, PRA, XNU 13.5, DEVELOPMENT, and keep-going enabled. Run 15 still appears queued.
- Run 43210924043 completed with build and artifact upload successful, but the linked-kernel guard failed because `llvm-nm | grep -q` closed the pipe early under `pipefail` (`LLVM ERROR: ... Broken pipe`). This was a verifier pipeline bug, not evidence that the symbol is absent.
- Updated the guard to let its producer streams finish, then run [43211905251](https://github.com/Kamion008/ios-pra/actions/runs/43211905251) completed successfully, including the linked-kernel guard, LSE check, and artifact upload. Artifact archive SHA-256: `cc96708d23f4b0c33534572028ea7744647d5922c5fb0861cc226f186e23c08c`.
- The downloaded archive matched that digest. Its extracted `kernel.development.pra` passed `SHA256SUMS` with SHA-256 `8d76ee0eb1d60739e9767b9bd38bf2456161aa9e4a8af46899574c75d63d898b`; it contains the `PRA-PREEMPT` diagnostic string. Packaging produced `shim/pra/outxnu/pra-xnu.img`, 5,980,160 bytes, SHA-256 `9addb712e1a924cf8c3e91e234a82b2d089b62f4bd2de829795692ca8a994171`.

## 0135 pinctrl driver status

- Review of the local `PRAPinctrl.cpp` and PRA config-table entry found read-only mapping of the four audited register windows, with no register writes. The delegated review made no changes.
- Compile replay is blocked because `/tmp/xnu-43018834356.log` and `/tmp/pra-buildtree` are absent. No `files.arm64` build-list entry or 0135 patch has been produced; the driver is not yet compiled or linked.

## Hardware result

- Latest run-17 trial: `shim/pra/outxnu/pra-xnu.img` (5,980,160 bytes; SHA-256 `9addb712e1a924cf8c3e91e234a82b2d089b62f4bd2de829795692ca8a994171`) was flashed only to the `kernel` partition. Fastboot returned `OKAY` for both sending and writing, printed its AVB-footer warning that partition size was zero, and returned `OKAY` for reboot.
- Post-reboot photo `PXL_20261112_120801399.jpg` shows the `Waiting on <dict ... IOMedia ... Apple_HFS ...>` line and early interface/driver initialization text. No panic is visible in the photo; no root mount or userspace boot is confirmed. The apparent ordering may include retained screen output, so do not infer that all visible lines belong to one boot sequence.
- A sandboxed fastboot attempt could not initialize libusb (`-99`). Retrying in elevated `bash` detected exactly one fastboot device.
- Hardware flash: `shim/pra/outxnu/pra-xnu.img` was written to the `kernel` partition; `Sending` and `Writing` both returned `OKAY`. Fastboot printed an AVB-footer warning that the partition size was reported as zero, but the write completed successfully.
- `fastboot reboot` returned `OKAY` after the flash.
- Runtime observation from `PXL_20261111_192201710.jpg`: early network-interface thread scheduling completes; the screen reaches `Waiting on <dict ... IOMedia ... Apple_HFS ...>`, then reports `preemption count not 0 on thread ... (1)`. The original panic string repeats the same message. The photo does not show a successful root-device mount or userspace boot.
- In the flashed image, the reported caller address `0xfffffff007420a1c` lies in the standard `preempt_count_notzero` symbol range (`0xfffffff007420a04` through `0xfffffff007420a48`). Disassembly of `return_to_user` in this kernel shows a direct branch to that panic stub, with no call to `_pra_preempt_notzero`; the kernel also lacks the `PRA-PREEMPT` string. The prior 0137 kernel artifact contains both the call and string. The 0138 buildtree source does contain the 0137 call, so its packaged kernel does not reflect the source shown in that buildtree. Investigate build outputs/rebuild behavior and add a linked-kernel assertion before another hardware flash.

## Later GPU research

- User supplied [Nik300/viva-gpu](https://github.com/Nik300/viva-gpu) as a useful reference for a later GPU investigation.


## 0139: Arasan SDHCI eMMC root driver (2026-11-12)

- New `xnu/patches/0139-pra-sdhci-emmc-root.patch` adds `bsd/dev/pra_sdhci.c`
  (PRA-only bdevsw, polled 512-byte PIO through the SDHCI buffer port, no DMA
  and no interrupts), registers it in `bsd/conf/files`, adds a
  `rd=sdhcroot0` branch to `IOFindBSDRoot`, and moves the `pra-emmc` ADT node
  to the absolute `0xFF390000` window. Writes stay gated on `emmcwrite=1`
  plus a `userdata` target; this trial is read-only.
- The register sequence is the one the EL1 diagnostic shim already proved on
  the phone when it read the GPT and wrote `misc`. The bootloader leaves the
  host clocked and the card in transfer state, so no card init is attempted.
- CI run [43219546138](https://github.com/Kamion008/ios-pra/actions/runs/43219546138)
  completed successfully. Artifact `kernel.development.pra` SHA-256
  `196c7db898474346790f9e2ebedbe5fb29857a91268f7b1b1e0383b1590a24ce`;
  it links `_pra_emmc_probe`, `_pra_emmc_rootdev`, `_pra_emmc_read_sector`,
  `_pra_emmc_strategy` and all 28 `PRA eMMC:` format strings.
- Packaged `shim/pra/outxnu/pra-xnu.img`: 5,986,304 bytes, SHA-256
  `1b8216f935d4c9df56313f454bfac8ff219372b764b40c3577fabf4baf6bc0a7`.
  Pre-flash checks: ADT `pra-emmc` reg `0xFF390000`, cmdline
  `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=sdhcroot0
  emmcroot=userdata emmcprobe=1`, embedded platform match `hisilicon,hi6250`.
- Flashed to the `kernel` partition only; `Sending`/`Writing`/`Rebooting` all
  returned `OKAY`. The user was AFK, so the screen result was not observed at
  flash time. Expected landing: `PRA eMMC:` host line, `GPT userdata
  first=10715136 sectors=...`, `/dev/sdhcroot0 ready`, `BSD root: sdhcroot0`,
  then an HFS+ mount failure on the existing Android data (read-only trial,
  nothing written). A photo is needed before claiming any runtime result.
- iPhone X (d22ap) iOS 16.7.16 20H392 root components are being fetched with
  `tools/pra-fetch-ipsw.sh` into the gitignored `research/ipsw-x/`
  (OS 4.73 GB, SystemOS 2.74 GB, AppOS 10 MB, DeviceTree.d22ap.im4p).
  `apfs-fuse` and `hfsprogs` are installed, so `tools/mkiosroot.sh` can build
  the HFS+ root once the files land. `research/ipsw-x/d22ap.adt` is then
  produced from `DeviceTree.d22ap.im4p` for the `/product` node.

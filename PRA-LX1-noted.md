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

## 0139 hardware result: eMMC read path proven (2026-11-12)

Photo `research/boot-photos/0139-hfs-mount-fail.jpg` (user-supplied, kept out of
git). On-screen lines, in order:

```
PRA eMMC: host base=ff390000 vers=0x1002 clock=7 present=ff7f8080
PRA eMMC: GPT userdata first=10715136 sectors=20062208 read-only
BSD root: sdhcroot0, major 1, minor 0
PRA eMMC: /dev/sdhcroot0 ready
hfs_ValidateHFSPlusVolumeHeader: unknown Volume Signature : 1020
hfs_mount: hfs_mountfs returned error=22 for device unknown-dev
cannot mount root, errno = 19
```

The boot got through the kernel-thread scheduling messages and then retried the
root mount four times with the same result. This is the expected probe result
and a full success for the driver: the polled PIO path read the GPT, selected
`userdata`, registered the bdevsw, and handed real sectors to HFS+. The volume
header at sector 2 is Android data (`0x1020`, not HFS+'s `HX`/`H+`), so HFS
rejected the volume and the root mount failed with ENODEV. Nothing was
written (`read-only` in the probe line).

Next hardware step is therefore not a driver fix: it is to put a real HFS+
image on `userdata` and boot again. That needs the iPhone X root image
(`tools/pra-fetch-ipsw.sh` is mirroring the 16.7.16 IPSW with aria2c, then
`tools/pra-build-iosroot.sh`, which needs root on the PC), staged with
`tools/pra-stage-iosroot.sh` from TWRP.

## Root image sizing decision: trim, keep the stock GPT (2026-11-12)

The whole IPSW is mirrored (`research/ipsw-x/`, 6,171,035,648 B) and the three
DMGs are mounted locally with apfs-fuse. Measured uncompressed payload:

```
OS root   8,291,487,156 B
SystemOS  3,360,034,133 B   (cryptex, hard-linked into the root)
AppOS         7,936,372 B
total    11,659,457,661 B = 10.86 GiB   vs p58 userdata 10,271,850,496 B
```

The stock GPT stays. `tools/pra-gpt-resize.py` / `tools/pra-flash-gpt.sh` exist
and were verified against the dump with sfdisk (drop preas/preavs/system/cust/
version/vendor/product, userdata becomes 13.68 GiB), but they are not used;
`research/gpt/stock-primary.bin` is a byte-identical copy of the current table.

`tools/mkiosroot.sh` now drops only data no first-boot UI loads (`MKROOT_TRIM=1`,
the default), keeping Setup.app, `OnBoardingBundles`, `/private/var/
staged_system_apps` (installd's first-boot app pass), Assistant, Health,
ScreenReader, Fonts and the en/it dictation bundles:

```
System/Library/PreinstalledAssetsV2   692 MB  voice/Siri/AirDrop/geo assets
System/Library/LinguisticData         880 MB  59 languages, en+it kept
usr/standalone/update                 170 MB  restore/update payloads
System/Library/NanoTimeKit            139 MB  watch faces
usr/share/tokenizer                    57 MB  CJK keyboard dictionaries
SystemOS *.symbols                    592 MB  dyld never maps them
```

Image is built to the whole partition (SIZE=9796M), so /private/var gets about
1 GiB (checked at build time: the pipeline fails below 200 MiB free).

Two targets, neither overwrites the other:

```
sudo tools/pra-build-iosroot.sh            # research/iosroot/ios16-root.img       (staged today)
sudo tools/pra-build-iosroot.sh --full     # research/iosroot/ios16-root-full.img (kept for a GPT resize)
```

Blocked on: root on the PC for the build (`sudo -n` is refused here), and the
phone has to be put in TWRP (stock kernel p30) for staging.

## fsck gate and the built trimmed image (2026-11-12)

The first complete build ran the whole pipeline: 8.6 GB copied in 83 s,
180,298 files and 132,967 folders, then the cryptex hard-links. `/private/var`
ended with **383 MiB free** (the 200 MiB guard passed). That is lower than the
earlier estimate because 4 KiB allocation-block rounding costs about 3 KiB on
average across 180k small files; nothing extra was copied.

The build then aborted on `fsck.hfsplus -f -n`:

```
   Volume header needs minor repair
(1, 0)
** The volume iOSRoot was found corrupt and needs to be repaired.
```

`(1, 0)` is `WriteError(E_VolumeHeaderDamaged, 1, 0)` ("invalid primary VHB"),
and `-d` says `result 35`, which is `EDEADLK` from hfsprogs' cache layer
("CacheRead: Deadlock"). It fires whenever the journaled attribute is set and
is reproducible on an **empty** `mkfs.hfsplus -s -J` image:

```
attributes 0x80002100 (cleanly unmounted | journaled | unused-node-fix)
fsck.hfsplus -f -y   -> "** The volume J appears to be OK."   exit 0
fsck.hfsplus -f -n   -> "Volume header needs minor repair (1, 0)"  exit 8
```

So it is a checker bug, not a filesystem defect. `tools/mkiosroot.sh` now
ignores exactly that pair in the read-only pass, fails on every other
complaint, and requires the `-y` pass to print "appears to be OK" or
"was repaired successfully" rather than trusting its exit code.

Verified on a copy of the real image: `-y` prints "appears to be OK" and the
only `-n` complaint is the artefact. Both volume headers are byte-identical,
the journal is empty, and the attributes are `0x80002100`.

Remaining free space is 383 MiB, which is the price of keeping
`staged_system_apps` (511 MB) and the first-boot UI. If setup hits ENOSPC the
next levers are the staged apps or `System/Library/Fonts/LanguageSupport`
(78 MB); the GPT resize (13.68 GiB) remains the clean fix.

## The recovery kernel always comes from p30 (2026-11-12)

hi6250 splits the boot image: `kernel` (p30, 24 MiB) holds the Linux kernel and
`recovery_ramdisk` (p32, 32 MiB) holds only a ramdisk. Every TWRP build for
Prague is therefore ramdisk-only (`kernel_size = 0`), including 3.5.2 and
7.0.0, which is why TWRP reports the stock kernel:

```
Linux localhost 4.4.23+ #1 SMP PREEMPT Mon Nov 2 17:32:05 CST 2020 aarch64
```

Confirmed two ways rather than assumed:

- The running `/proc/cmdline` is exactly p30's boot-image cmdline. TWRP's own
  header declares `cmdline=buildvariant=eng`, and that string appears nowhere.
- A probe image in p32 built from the **stock kernel gzip** (UTS_RELEASE
  patched to `4.4.23X`, TWRP ramdisk, p30's load addresses) dropped the
  bootloader into `ERROR MODE`. Restoring the p32 backup brought TWRP back
  byte-identically. With a kernel present in p32 the bootloader rejects the
  slot; with `kernel_size = 0` it takes kernel+cmdline from p30 and only the
  ramdisk from p32.

Consequence: a dual boot cannot come from p32. Either p30 carries a kernel
that can kexec XNU, or the p30 loader itself boots Linux on demand. The second
is attractive because the loader already reads the GPT and the bootloader
attaches the p32 TWRP ramdisk + `/chosen/linux,initrd-*` when the recovery
keys are held, so the loader can simply branch on the presence of an initrd.
`erecovery_kernel` (p27, 24 MiB) is unused and is the natural home for the
11.2 MiB stock `Image.gz`; it is dd-able from TWRP even though `fastboot flash`
blocks it.

PRA GPT for reference: `misc` p20, `erecovery_kernel` p27, `kernel` p30,
`ramdisk` p31, `recovery_ramdisk` p32, `system` p53, `vendor` p56,
`userdata` p58.

## 0139 first XNU boot: HFS+ read path works (2026-11-12)

`debug=0xc ... rd=sdhcroot0 emmcroot=userdata emmcprobe=1` (no `emmcwrite`)
reaches XNU and the certificate path, then mounts the volume far enough to
read the volume header:

```
PRA eMMC: GPT userdata first=10715136 sectors=20062208 read-only
BSD root: sdhcroot0, major 1, minor 0
hfs: Initializing the journal (joffset 0x4f000 sz 0x800000)...
jnl: b(1, 0): do_jnl_io: strategy err 0x16
jnl: b(1, 0): journal_create: failed to write journal header.
hfs: late jnl init: failed to open/create the journal (retval 0)
hfs_mountfsplus: hfs_late_journal_init returned (22)
hfs_mountfs: hfs_mountfs returned error=22 for device unknown-dev
cannot mount root, errno = 19
```

So eMMC, GPT, the HFS+ volume header, block size, journal offset and size are
all correct. The mount stops because `hfs_vfsutils.c` deliberately exempts the
root filesystem from the read-only journal skip:

```c
if ((hfsmp->hfs_flags & HFS_READ_ONLY) &&
    (vfs_flags(hfsmp->hfs_mp) & MNT_ROOTFS) == 0) { ... journal_is_clean ... }
```

A read-only root therefore goes on to `journal_create()`, which writes one
512-byte header through the **raw device** (`jnl: b(1, 0)`), not through the
filesystem, so the write gate in the bdevsw driver is what rejects it. The
volume itself has `kJIJournalNeedInitMask` set, which is normal for a volume
built by `mkfs.hfsplus`: macOS initialises the journal on first mount.

Next step is `emmcwrite=1 rootrw=1`, which lets that header write through and
mounts the root read-write (`/private/var` lives on the root, see 0031).
`tools/pra_package.sh` re-packages the CI kernel with a new `CMDLINE`; the
boot args live in the payload, not in the Android boot header.

### Result: root mounts read-write, launchd dies on code signing

`cmds emmcwrite=1 rootrw=1` completes the whole storage stack:

```
PRA eMMC: host base=ff390000 version=1002 clock=7 present=1fff0000 power=0
PRA eMMC: GPT userdata first=10715136 sectors=20062208 writable
hfs: Initializing the journal (joffset 0x4f000 sz 0x800000)...
hfs: mounted iOSRoot on device b(1, 0)
hfs: set VeryLowDisk: freeblks:98201, dangerlimit:125365
A5XELTE: root volume is not authenticated (error 25); continuing unsealed
load_init_program: attempting to load /sbin/launchd
panic(cpu 0 ...): unexpected SIGKILL of launchd (CS_KILLED)
    namespace 9 code 0x8e description none
```

So the 512-byte journal header write through the polled single-sector path
works, HFS+ mounts the 9.79 GiB volume read-write, and launchd is found and
exec'd. The panic is the same one the donor port documented in `NOTES.md:174`,
where `namespace 9 code 0xe` is `OS_REASON_EXEC / EXEC_EXIT_REASON_WRONG_PLATFORM`:
the kernel is built `XNU_TARGET_OS_OSX`, so an iOS-platform binary with no
`posix_spawnattr` platform is treated as alien and refused, killing init.

The fix is a boot arg, not a code change - `unentitled_ios_sim_launch=1`
(`TUNABLE(bool, unentitled_ios_sim_launch, ...)` in `bsd/kern/kern_exec.c:196`,
DEBUG/DEVELOPMENT only, and the CI kernel is `kernel.development.pra`). The
donor's working set also carries `launchd_unsecure_cache=1 ignition_level=1
wdt_test=no_user_checkin wdt=-1` (`NOTES.md:41`), so PRA uses:

```
debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress
rd=sdhcroot0 emmcroot=userdata emmcprobe=1 emmcwrite=1 rootrw=1
unentitled_ios_sim_launch=1 launchd_unsecure_cache=1
ignition_level=1 wdt_test=no_user_checkin wdt=-1
```

Note the `0x8e` vs the donor's `0xe`: same low byte, so the same
`EXEC_EXIT_REASON_WRONG_PLATFORM`; treat the source enum, not the printed
value, as authoritative.

## Loader-based dual boot

The p30 loader now branches on the recovery initrd instead of always entering
XNU. `vol+` at power-on makes the Huawei bootloader attach the TWRP ramdisk
and add `/chosen/linux,initrd-start` = `0x11000000` / `linux,initrd-end` =
`0x11e80000` to the live DTB. `pra_linux_try()` walks the FDT (4- or 8-byte
cells) and, when both properties are present and sane, tries the staged
Image. A normal boot has no such properties and reaches the XNU path with no
extra reads and no console output from the new code.

Scratch layout in `preas` (p51, first absolute LBA 2097152, 880 MiB):

| Offset | Content |
| --- | --- |
| LBA 2097152, 512 B | `struct pra_linux_header` (`PRALNX01`, version 1) |
| +512 .. +2 MiB | zero; keeps the Image start on a 2 MiB boundary |
| LBA 2101248 (= 0x40200000) | uncompressed arm64 `Image` |

The header carries `header_size` 512, `image_lba` 2101248 (checked against the
compile-time constant), `image_size`, a zlib CRC-32 of exactly those bytes,
`flags` 0 and `load_addr` 0x30000000. Any mismatch, a blank page or a failed
CRC returns to XNU; the loader never writes storage and never reads p30 or
p58. The constants and the struct live in `shim/pra/linux_boot.h`, and
`tools/pra-stage-twrp-kernel.sh [P30_DUMP]` extracts the Image from p30's
Android boot image v0 (`kernel_size` at 8, page 2048, gzip at 2048),
gunzips it, writes header + Image to p51 with toybox `dd bs=1048576`, and
compares a SHA-256 readback. It refuses to run outside TWRP and refuses to
write unless p51 still starts at LBA 2097152 (and, when it has to read p30
itself, unless p30 still starts at 901120 and is 24 MiB).

Load placement follows the arm64 boot protocol, which aligns the base
address, not `text_offset`: the Image goes to `0x30000000 + text_offset` and
the entry is that same address (the Image's first instruction is a branch).
Modern kernels have `text_offset` 0 and land at 0x30000000; the stock 4.4.23
Image is expected to report 0x80000 because Huawei's released 4.4 source sets
`TEXT_OFFSET := 0x00080000`, so it would land at 0x30080000. (That header
value was not read from a p30 dump in this session.) A literal
`text_offset % 2 MiB == 0` check would reject that stock Image, so the loader
instead requires `text_offset < 2 MiB` and checks the resulting placement. It
also validates the `ARM\x64` magic at byte 56, that the effective
`image_size` is at least the file size and fits the low bank, and that neither
the image nor its BSS overlaps the initrd or the DTB.

The window cannot collide with recovery state: the ramdisk is at 0x11000000
and ends near 0x11e80000, the live DTB is around 0x07e00000, the loader and
its appended XNU payload occupy 0x480000..~0x1500000, and the display
scanout is at 0x5D000000. Even 128 MiB above 0x30080000 ends at 0x38080000,
leaving a ~0x25000000 gap to the framebuffer and staying below the
0x60000000 end of the first RAM bank.

Reads reuse the proven polled SDHCI CMD17 path (`shim/pra/sdhci_read.c`,
mirroring `probe.c`), one 512-byte sector at a time, read-only. A 35 MB Image
is about 70,000 commands, so the loader stops the bootloader watchdog first
(the same WDT sequence `probe.c` uses) and prints a progress line every
4 MiB. The bulk transfer happens only after the first sector validates, so a
wrong image fails after one command. The Image and DTB are cleaned to the
point of coherency, then `linux_jump.S` enters with x0 = DTB, x1..x3 = 0, and
SCTLR_EL1.M/C/I cleared.

Verified locally: the loader builds with the existing
`shim/pra/build-xnu.sh` (clang, `-Werror`), `loader.bin` is 12,056 bytes and
`pra-xnu.img` is 5,992,448 bytes. Untested: the actual Linux jump. No device
was attached, so nothing here establishes that the stock 4.4.23 kernel
accepts this handoff at 0x30080000, that its decompressed Image the script
extracts has the assumed header fields, or that the 70,000-read transfer
finishes reliably. `xnu/patches/*` is untouched.

## Persistent console log (0140)

The UART is gated by EL3 and the framebuffer console wraps back to the top,
so the last lines of a hung boot are lost and the photo only ever shows the
truncated line where output stopped. Patch `0140-pra-console-ring-log.patch`
keeps `_cnputs` bytes in a 4 MiB ring in `bsd/dev/pra_sdhci.c` and a kernel
thread flushes it every 10 s to `erecovery_kernel` p27 (absolute LBA 753664,
24 MiB): sector 0 is a `PRALOG1` header with `total`/`seq`, sectors 1..8192
are the ring. Only `erecovery_kernel` is written, and only its first 8193
sectors; the filesystem write gate in `pra_emmc_write_sector` is unchanged
(`pra_emmc_write_raw` is now shared, `pra_log_write_sector` range-checks and
takes the same lock per sector so a 4 MiB flush cannot stall HFS).

Boot args:

- `pralog=1` - keep the ring and flush it (no extra console output).
- `praloghalt=1` - at probe, print the previous boot's tail from p27 and halt
  (stays on screen; for a hang where nothing else can run).
- `pralogat=<s>` - print the in-memory tail and halt `<s>` seconds after the
  log starts. Deterministic capture of the current boot.
- `pralogidle=<s>` - same, after `<s>` seconds without new console output.

Trade-off: p27 holds the stock eRecovery kernel, so eRecovery stops working
once the log is enabled. That is acceptable here - eRecovery must never be
used on this device (it can wipe userdata) - and nothing else reads p27.

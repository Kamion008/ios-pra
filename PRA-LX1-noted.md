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

### 0140 rev 2: capture every console path, survive a busy card (2026-11-12)

`0140-pra-console-ring-log.patch` was rewritten in place, same number, because
CI copies `xnu/patches/*.patch` into the donor tree and applies them in
numeric order against the tree the previous patch produced: a new number
would have to re-derive 0140's hunks on top of the old ones. Rev 2 was made
by reverse-applying rev 1 into a scratch copy to get the post-0139 tree,
editing, and diffing back; forward and reverse both reproduce the trees
byte-exactly, and the brace balance of both touched files is (0, 0) as in the
base.

- The ring hook moved from `_cnputs` to `_cnputc`, declared above `_cnputc`
  instead of where rev 1 put it. Rev 1 stopped at `exec mount` with `seq=1`
  even though the tty path reaches the ring through
  `console_ring_try_empty` -> `_cnputs`, so the capture was not the only
  suspect. `_cnputc` is the one place every path lands: `_cnputs` loops
  through it once per character, `console_write_char` and the ring flush
  reach it without `_cnputs`, and the hook sits after the `\r` expansion so
  the ring holds the sequence the framebuffer drew rather than the logical
  one. `pra_log_append(&c, 1)` per character keeps that path free of locks
  and of device I/O. `disableConsoleOutput` is only TRUE while the graphics
  console is paused, and console text is on the screen throughout these
  boots, so nothing observable is lost by dropping the chunk hook.
- `pra_log_thread` no longer `return`s on a failed write. With `rootrw=1` the
  HFS driver writes through the same SDHCI channel without taking
  `pra_emmc_lock`, so the flusher can meet a card that is busy mid transfer
  (EBUSY). `flushed` now stays where it is and the next 10 s tick rewrites
  those blocks, so one transient busy cannot end the loop and hide the
  `pralogidle` and `pralogat` dumps that make a hang readable at all.
  Complaints are bounded to the first 8 plus every 64th tick.
- Source state only: CI has not built this revision yet, so nothing about
  this revision has been verified on hardware.

## Dual boot flash of the rev-1 loader image (2026-11-12)

- p30 was stock at the start of this session: `sha256`/`md5` of
  `/dev/block/mmcblk0p30` read over TWRP matched the read-only stock dump
  (`82e4855fd0f04b9b2ede301b0ec7452f`). Consequence, checked rather than
  assumed: power-on ran the stock Linux kernel, so only recovery gave TWRP
  and XNU did not load on a plain reboot.
- `shim/pra/outxnu/pra-xnu.img`, 5,992,448 bytes, SHA-256
  `6f4a1581b83d8eb0bd0649c4ae892f639c94b78917e626f5215c0105345e5d97`, is the
  rev-1 build: the dual-boot loader (`loader.bin` 12,056 bytes, with
  `linux_boot.o`, `linux_jump.o` and `sdhci_read.o`) plus 0140 rev 1. Checked
  before flashing: `ANDROID!` v0 header, kernel gzip at 2048, and
  decompressing that gzip yields the 17,006,592-byte payload holding the
  whole boot-arg line, `rd=sdhcroot0` through `pralog=1 pralogat=120`.
- Flashed to the `kernel` partition with the PRA serial selected (the Pixel
  attached alongside it stayed untouched). `Sending` and `Writing` both
  returned `OKAY`, with the usual AVB-footer warning that reports the
  partition size as 0, and `fastboot reboot` returned `OKAY`.
- That boot did not reach XNU: the phone showed ERROR MODE, and holding `vol+`
  did not reach TWRP either. The cause is in the next section: the loader
  treated any boot with an attached initrd as recovery, and the ordinary
  power-on has one too, so it took the untested Linux branch. The read-only
  stock dump `mmcblk0p30.bin` (24 MiB, md5
  `82e4855fd0f04b9b2ede301b0ec7452f`) was written back to `kernel`; TWRP
  `3.5.2_9-0` came back and `md5sum /dev/block/mmcblk0p30` then matched the
  dump exactly, so the restore path from fastboot is proven.
- The one device-side variable that changed between the last XNU boot of this
  same image and this failure is the staged Linux Image in p51 (written at
  17:54, after the boot that produced the p27 log). That makes the Linux
  branch reachable for the first time, and that branch was never exercised:
  its 70,000-sector polled read and the stock 4.4.23 handoff at 0x30080000
  are untested. A hang there would also explain ERROR MODE on a plain reboot,
  because Huawei's bootloader counts failed boots and latches ERROR MODE once
  the count runs out. Not established yet: whether it hung in the header
  read, the Image transfer, the CRC, or the jump. The loader prints
  `PRA XNU loader`, `linux: recovery initrd present`, `linux MiB <n>`,
  `linux: CRC mismatch` and `jumping to Linux` on the framebuffer, so the
  last line visible on the failed attempt discriminates those cases.
- Do not flash this loader image to p30 again until the Linux branch is
  either shown to return to XNU or made to fail closed before the jump.

## Recovery gate: the initrd is not recovery-specific (2026-11-12)

Read from the live DTB in TWRP, `/proc/device-tree/chosen/bootargs`, on a
card-attached `vol+` boot:

```
enter_recovery=1 enter_erecovery=0 androidboot.mode=normal
recovery_update=1 normal_reset_type=VolUsbUpdate
linux,initrd-start = 0x08000000
linux,initrd-end   = 0x0c9c9d00   (~76.8 MB)
```

- `androidboot.mode` is `normal` in a recovery boot, so it cannot select the
  branch. The token that does is `enter_recovery=1`.
- The measured initrd range differs from what the loader comment assumed
  (0x11000000..0x11e80000, ~15.2 MB). The loader only requires the range to
  sit inside the first RAM bank, so it accepts both.
- The loader selected Linux on the initrd alone, and an ordinary boot
  attaches the Android ramdisk the same way. That is why staging `preas`
  (p51) acted as the real trigger: with p51 blank the branch declined and
  XNU ran, and with a valid staged Image it jumped to a Linux handoff that
  has never worked.

Fix: `pra_linux_try` now requires the exact space-delimited token
`enter_recovery=1` in `/chosen/bootargs` before it even looks at the initrd,
and declines otherwise, so a boot that is not recovery cannot take the
staged Image even when the header and CRC are valid.

- Host unit test: the FDT helpers and `bootarg_has` are extracted verbatim
  from `linux_boot.c` into a test that builds synthetic DTB blobs. All 8
  cases pass, including `enter_recovery=0`, `xenter_recovery=1`,
  `enter_recovery=10`, a missing `bootargs` property, and
  `androidboot.mode=normal` on its own.
- Rebuilt loader 12,504 bytes; `pra-xnu.img` 5,994,496 bytes, SHA-256
  `dc06157485481053f752776364f0234b86c26c9c9c7989f076300a21c6865fae`. The
  appended XNU payload is byte-identical to the previous build
  (`sha256(payload[0x500000:])` `8b0f2302...`), so only the loader changed
  and the kernel under test is the same one that reached launchd.
- Written to p30 from TWRP with `dd bs=1048576`, then read back over 11,708
  sectors and compared: exact match to the local file.
- `adb reboot` from TWRP with this build then showed ERROR MODE again. That
  is not yet a normal cold boot: the earlier XNU boots were power-ons from
  off, and a reboot issued inside recovery may carry recovery state through,
  in which case the gate is legitimately satisfied and the Linux branch is
  what fails. The discriminating evidence is the loader's own framebuffer
  text (`jumping to XNU` versus `linux: recovery initrd present` /
  `jumping to Linux`) plus a cold power-off/power-on with the same image.

## ERROR MODE is the boot-failure latch in p48, not misc (2026-11-12)

Every custom image in `kernel` (p30) started returning ERROR MODE, including
the pre-`linux_boot` image that had booted XNU earlier the same day, while the
stock p30 dump still booted TWRP every time. Device state, not loader code.

What the phone reports in a TWRP boot at that point:

```
enter_recovery=1 enter_erecovery=0 androidboot.mode=normal
recovery_update=1 normal_reset_type=VolUsbUpdate format_data=1
reboot_reason=coldboot   last_bootup_keypoint=34   boot_slice=0x0008c82f
```

- `enter_recovery=1` is present with **no keys held** and after a plain
  `fastboot reboot`, so the bootloader is entering recovery on its own. That
  is the failure path, not a key-combo artefact.
- `misc` (p20) is **entirely zero** — no `bootloader_message`, no
  `boot-recovery` command, no boot counter. Dumped and checked byte by byte.
  So the usual Android `misc` latch does not exist on this port.
- `p47 patch` is empty (first 64 KiB zeros), so `boot_slice` is not applying
  kernel patches.

The state lives in **p48 `bootfail_info`** (2 MiB, LBA 1998848):

```
magic "XIFB" (BFIX)  u32[1]=0x14=20 records  u32[2]=0x1000=4096 slot size
slot n at n*4096: u32 timestamp, then a per-boot status word pair
```

20 records, one per boot, timestamps from 2026-11-11 09:53 through
2026-11-12 16:16 UTC. Seventeen of them share the signature
`0x03000003 / 0x02000004 / 0 / 1 / 7`, i.e. one per XNU boot: **XNU never
reports boot success**, so LK keeps counting failures, eventually forces
recovery, and with `erecovery_kernel` (p27) overwritten by the 0140 console
ring the forced-recovery handoff has no valid kernel — ERROR MODE.

Evidence that the latch is a counter and not per-image: the stock p30 image
is the same bytes in both cases `md5 82e4855fd0f04b9b2ede301b0ec7452f`, and
it boots TWRP even with the counter full, because the recovery boot itself
is the latch's escape hatch.

- Backed up p48 and p49 before touching them:
  `/mnt/giochi/pra-lx1-handoff/dump/mmcblk0p48.bootfail_info.2026-11-12.bin`
  and `mmcblk0p49.rrecord.2026-11-12.bin`. p49 `rrecord` is the reset log and
  its newest entry is `boot-erecovery`, consistent with the forced path.
- Zeroed p48 (`dd if=/dev/zero bs=4096`, whole 2 MiB) from TWRP; readback md5
  equals 2 MiB of zeros. This is Huawei's standard bootloop reset and only
  loses failure bookkeeping.
- Then, still inside TWRP, wrote the no-Linux-branch image to p30
  (`pra-xnu-launchd.img`, sha256 `1a65b12a…`, readback over 11,692 sectors
  exact) and powered off, so the next start is a real cold boot and no
  Android boot can consume the HFS+ userdata.

Consequence for the design: XNU has to clear this latch if it is going to be
the default boot, otherwise every boot burns a failure slot until LK forces
recovery again. `bootfail_info` is a plain GPT partition (p48, LBA 1998848),
so the loader can zero its first sector or rewrite the magic before handing
off to XNU — the same `sdhci` write path 0139 already uses for p30/p27. A
minimal version is enough: write zeros over the 4 KiB header sector so LK
reinitialises the counter on each XNU boot.

## The bootloader is in its eRecovery failsafe, and that reads p27 (2026-11-12)

The ERROR MODE screen finally named itself:

```
Error!
Func NO: 11 (recovery image)
Error NO: 2  (load failed)
```

Meaning of the evidence collected since:

- `misc` (p20) is all zeros, p47 `patch` is empty, and nothing in p7 `nvme`
  (three identical NV copies, 95 items, `BOOTINF`/`POWSTA`/`WVLOCK`/`FBLOCK`
  only) carries a boot-fail counter. Clearing p48 `bootfail_info` changed
  nothing.
- LK still boots with `enter_recovery=1` and no keys held, i.e. it is latched
  into the recovery path and this is not a key-combo state.
- Writing a known-good image into p27 (`pra-diag.img`) turned the ERROR MODE
  into that image's own red fill on the next power-on, which proves the
  failsafe *loads and jumps to p27*, not to `kernel` (p30). The diag then
  hangs in its register probes (it paints `0x5D000000` red before anything
  else), which is why the screen stayed red instead of resetting to TWRP.
- With the stock p30 dump in p30 and our diag in p27, a cold power-on still
  showed the diag: so when p27 is loadable, LK never reaches p30. When p27
  held the `PRALOG1` ring log, the same path produced `Error NO: 2` instead.
- Conclusion: the ERROR MODE was never about the XNU kernel at all. Our
  console-ring log destroyed the image LK actually boots on every power-on,
  and every custom p30 image since then was never even read.

Recovery of the chain: `pra-xnu-rw-raw.img` (the proven `639af15e` payload,
repacked with a raw arm64 Image instead of gzip, 17,008,640 bytes, sha256
`76190b67…`) was written to p27 (`dd bs=1048576`, readback over 33,220
sectors exact) with stock p30 still in `kernel`. A cold power-on then boots
XNU: the loader draws its text and the kernel starts.

Two consequences that shape the next steps:

- The XNU root stays bootable during bring-up even while LK is latched, and
  p27 is a valid scratch target as long as the payload boots from it does
  not write p27 itself (no `pralog=1` in the cmdline).
- The intended layout (XNU in p30, Linux/TWRP as the recovery branch) needs
  the latch cleared, otherwise p30 is dead weight. The latch is not in p16
  persist, p20 misc, p48 bootfail_info or p7 nvme; the remaining candidates
  are the `oeminfo`/`reserved*`/`dfx` partitions and `boot_slice`.
- p27 now holds the XNU image, so the eRecovery log target is gone from that
  partition. 0140 must not be pointed at p27 again while p27 is the boot
  image; move the ring into `preas` p51 or a dedicated area first.

## launchd gets past code signing with the launchd payload (2026-11-12)

Booting `pra-xnu-rw` (payload `639af15e`, cmdline without the launchd args)
from p27 reached launchd and then panicked:

```
load_init_program: attempting to load /usr/appleinternal/sbin/launchd.development
load_init_program: attempting to load /sbin/launchd
panic(cpu 0 caller ...): unexpected SIGKILL of launchd (CS_KILLED)
  reason -- namespace 9 code 0x8e description none
```

- Namespace 9 is `OS_REASON_EXEC` (`bsd/sys/reason.h`). The kill comes from
  the exec/codesigning path in `kern_exec.c`: on signature failure it sets
  `CS_KILLED` and sends SIGKILL, and `kern_sig.c` treats a SIGKILL of
  `initproc` as fatal by design. `A5XELTE: root volume is not authenticated
  (error 25); continuing unsealed` is the preceding line, i.e. the volume has
  no authenticated root hash, so launchd has no trusted cdhash.
- The fix is the payload, not a new kernel change: `pra-xnu-launchd.img`
  (payload `9d40b2d3`, cmdline with `unentitled_ios_sim_launch=1
  launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin
  wdt=-1`) boots from p27 and walks past launchd into userspace. Observed:
  `exec mount`, then `exec softwareupdated`. So the earlier "silence after
  exec mount" was this kill/panic, and the later `0140` build (`8b0f2302`)
  reached the same point because it also carries those args.
- `unentitled_ios_sim_launch` is a `TUNABLE` in `bsd/kern/kern_exec.c`
  (`#if XNU_TARGET_OS_OSX`), so the kernel under test is a DEVELOPMENT build
  as expected. `launchd_unsecure_cache` and `ignition_level` are not in this
  tree; they are consumed outside kernel/bsd.
- Image used: `pra-xnu-launchd-raw.img` (raw repack of the same flat image,
  17,008,640 bytes, sha256 `ff856fc1…`), written to p27 and verified over
  33,220 sectors. Raw is used because LK in this path loads p27 directly and
  no decompression step is needed.
- Boot arrangement while the latch is unresolved: p30 = stock dump,
  p27 = XNU image, plain power-on boots XNU through LK's failsafe, and
  holding vol+ at power-on (cable unplugged) still reaches TWRP for writes.

### 0140 and the p27 boot image conflict

Since LK's failsafe now boots p27, the 0140 ring log must not point at p27:
a kernel with `pralog=1` flushes over its own boot image, which kills the
next power-on (LK would read half a ring buffer where the image was). Until
the ring is moved, boot XNU from p27 only with payloads whose cmdline has no
`pralog=1` — `pra-xnu-launchd` (`9d40b2d3`) is the known-good one and
`pra-xnu-rw` (`639af15e`) lacks the launchd args and panics.

Moving the ring into free space in `preas` (p51) is the clean fix: the
staged Linux header and Image occupy LBA 2097152 and 2101248 plus ~71,000
sectors, so a ring at, say, LBA 2199552 does not overlap them. That is a
0140 code change (`pra_log_erecovery_lba`) plus a rebuild, not a runtime
setting.

## SMP is already wired; only `cpus=1` holds it back (2026-11-12)

Nothing in the tree needs to be written to run more than one core:

- `machine_routines.c` clamps `cpus=N` to `SWEET_SMP_MAX_CPUS` (8) and PRA.h
  already defines SWEET/A5XELTE, so the SMP topology parser builds all eight
  entries from `mkadt_pra.py`'s `/cpus` nodes (MPIDR 0..3 and 0x100..0x103).
- `iokit/Kernel/arm/SweetCPU.cpp` is the A5XELTE implementation:
  `startAll` starts each `processor_start()` and waits for `initCPU`, which
  sends a self-SGI through the GICv2 memory-mapped interface
  (`a5xelte_send_self_ipi`) and verifies `cpu_signal`; `startCPU` issues
  `PSCI CPU_ON` (SMC, SMCCC 1.0) with the physical address of
  `sweet_secondary_entry` in `osfmk/arm64/start.s`.
- `cpu_start()` already cleans `CpuDataEntries`, `CpuData`, `ResetHandlerData`,
  `BootArgs`, `sysreg_restore`, `cpu_ttep` and `bootstrap_pagetables` to PoC
  before CPU_ON, which is what `sweet_secondary_entry`/`LowResetVectorBase`
  need with the MMU off.
- `pexpert/arm/pe_fiq.c` runs `pe_init_fiq()` per CPU (`PE_init_cpu()` in
  `arm_cpu_init()`), maps the GICv2 pair from the ADT (`0xE82B1000` /
  `0xE82B2000` offsets from SOC_BASE) and records each core's banked
  `ITARGETSR0` mask for later cross-CPU SGIs.

So the whole SMP path is present and only the boot argument `cpus=1` in the
payload keeps seven cores parked. `cpus=4` selects the four 2.1 GHz cores of
cluster 0 (logical 0..3, MPIDR 0..3); `cpus=8` adds cluster 1 (MPIDR
0x100..0x103).

Because the cmdline lives in the payload header (`tools/mkpayload.py`,
`CMDLINE = 0x48`), it can be changed without rebuilding the kernel: in the
raw boot image the payload starts at file offset `2048 + 0x80000` and the
cmdline at `+0x48`. `pra-xnu-smp4-raw.img` and `pra-xnu-smp8-raw.img` are the
known-good launchd image with only that one byte changed (`0x80860`, `1` ->
`4`/`8`), SHA-256 `b438c2e8…` and `b5aa1d2e…`.

Risks to watch on the first multi-core boot (all visible on the fb console):

- `PSCI CPU_ON rc=` non-zero (`-3` = NOT_SUPPORTED, `-4` = INVALID_PARAMS)
  means the ATF conduit differs (HVC vs SMC) or rejects the entry address.
- `cpu=N startup timeout (reset/MMU/GIC/SGI)` means the core was powered on
  but never reached `initCPU`; the entry/MMU/GICv2 ordering is then next.
- `cpu=N NOT registered (IOKit matching timeout)` means the ADT CPU node did
  not match the SweetCPU driver (MPIDR/logical-id mismatch).

Since the ring log writes p27 and p27 is the boot image, test these without
`pralog=1`; the fb console is the log.

## SpringBoard's 0x0 display is a missing AppleCLCD match (2026-11-12)

The launchd payload's userland boot is alive but SpringBoard never stays up:

```
STR *** Terminating app due to uncaught exception 'NSInternalInconsistencyException',
    reason: 'We expect a valid bounds for configuration: <FBDisplayConfiguration'
STR CRDisplay.name = Wireless;
STR CRDisplay.deviceName = wireless0;
STR CRDisplay.currentMode = <FBDisplayMode: 0x...; 0x0 0Hz sRGB SD...>
STR bounds = {{0, 0}, {0, 0}};
CRASH SpringBoard Reason ns 2 code 0x6! (none)      # SIGABRT
SpringBoard crashed: Too many corpses being created.
```

- `ns 2 code 0x6` is `OS_REASON_SIGNAL` / SIGABRT, i.e. the exception above.
  launchd then refuses to respawn SpringBoard ("Too many corpses being
  created") and the phone keeps cycling xpcproxy/fairplayd/bluetoothd.
- `CRDisplay.name = Wireless` / `deviceName = wireless0` is CoreDisplay's
  *virtual* display placeholder. The real display never appeared because the
  kernel never published an `IOMobileFramebuffer`.
- Root cause: the AppleCLCD personality in `iokit/KernelConfigTables.cpp`
  matched only `samsung,a5xelte-display` / `samsung,dreamlte-display` on an
  A5XELTE build, but `tools/mkadt_pra.py` publishes `/arm-io/disp0` as
  `hisilicon,hi6250-display`. No match -> `SweetFramebuffer.cpp` never starts
  -> no IOMobileFramebuffer -> CoreDisplay invents the 0x0 wireless display.
- Fix: patch `0141-pra-display-name-match.patch` adds
  `'hisilicon,hi6250-display'` to that IONameMatch list for
  `ARM64_BOARD_CONFIG_PRA` (next to the a5xelte/dreamlte names). The driver
  itself already handles PRA: `AppleCLCD::start` uses `A5_FB_PHYS`
  (0x5D000000), `A5_FB_WIDTH/HEIGHT` (1080x1920) and `A5_FB_STRIDE` (4320)
  from PRA.h, and reports `SWEET FB: AppleCLCD ...` when it starts.
- Consequence: the fb console never gives way to CoreAnimation yet. Once
  AppleCLCD matches, its first swap mutes the text console
  (`sweet_console_muted`) and publishes the 1080x1920 surface.

The display fix needs a kernel rebuild, so it rides with the SMP test:
`CMDLINE='... cpus=8 ...' tools/pra_package.sh out/ci/kernel.development.pra`.

### cpus=8 panics registering the second cluster (known from A5XELTE)

The PRA 8-core trial printed exactly the sequence the SMP code wants:

```
A5XELTE CPU: requested=8 selected=8 (limit=8)
A5XELTE CPU: cpu=0 mpidr=0x0 came alive; SGI1 OK
A5XELTE CPU: cpu=1 CPU_ON target=0x1 entry_pa=0x89425000 context=1
A5XELTE CPU: cpu=1 PSCI CPU_ON rc=0
panic(cpu 0 caller ...lock_ticket.c:143): Ticket lock 0xfffffff007b70880
  is unexpectedly owned by thread 0xfffffff65a54c820
```

- `0xfffffff007b70880` is `pset0 + 0x100`, i.e. `pset0.sched_lock`
  (`lck_ticket_t`). The panic is the recursive-acquire detector in
  `lck_ticket_contended` (`cthread->ctid == tlock->lck_ticket_owner`).
- This is not a PRA surprise: `A5XELTE_PROGRESS.md` records the same result
  on the Exynos donor — "the eight-core trial reached CPU1 but panicked on
  CPU0 with an unexpectedly owned ticket lock while registering the second
  physical cluster. Selecting cpus=4 on the same eight-core-capable source
  instead produced a user-visible 4/4 CPUs initialized, SGI1 verified."
- So PSCI `CPU_ON` and the CPU1 entry path work on PRA (rc=0, CPU0 SGI1 OK);
  what breaks is bringing up cluster 1 (MPIDR 0x100..0x103). `cpus=4`
  selects cluster 0 (MPIDR 0..3, the 1.7 GHz cluster per
  `mkadt_pra.py`; cluster 1 is the 2.1 GHz one) and avoids it.
- Practical layout: `cpus=4` now for a 4x speedup; cluster 1 is a separate
  debugging item (suspects: per-cluster `ml_processor_register` path,
  `cluster_type`/cluster-id bookkeeping, or the second cluster's
  `pset_update_processor_state` racing the boot CPU's startAll).

### The Linux branch trigger was LK's own flag (`pra_linux=1` now)

The 4-core + display-fix image booted to a black screen that printed only
`linux MiB4` / `jumping to Linux`. The loader gate was
`enter_recovery=1`, which LK's eRecovery failsafe sets **itself** on every
power-on while it stays latched — the same reason p27 is what gets booted.
So the gate was always true and the loader went to the staged Image in p51
every time.

`shim/pra/linux_boot.c` now requires the exact token `pra_linux=1`, which
nothing in the boot chain sets today, so the branch is inert and fails
closed to XNU. It stays as an explicit opt-in hook for a future dual-boot
trigger (misc flag or key state read by the loader) once one exists.
`bootarg_has()` is inlined and the token is folded into immediates, so the
string does not appear in `loader.bin`; verify a rebuild by loader size/time
instead of `strings`.

Raw image with the fixed gate, 4 cores and 0141: `pra-xnu-smp4-raw.img`
(`74886924107df63440c62e022770a117cd729df733b28acc93967f3217128d39`),
written to p27 and read back over all 33,220 sectors.

### Slow userland: the root read path was one CMD17 per 512 bytes (0142)

With display and 4 cores working, the remaining "this is slow" is mostly the
root filesystem, not the CPU. `pra_sdhci.c` read every 512-byte sector as its
own CMD17: full command setup, a poll for command complete, an R1 check and a
second poll for buffer-ready. An iOS 4 KiB page-in therefore paid that eight
times, and every page fault in a 450 MiB machine pays it too.

Patch `0142-pra-sdhci-multi-block-read.patch`:

- one CMD18 per read chunk, up to 64 sectors (32 KiB), with block-count
  enabled and auto CMD12 (`TRANSFER_MULTI_READ` = 0x36), draining one 512-byte
  block per `BUFFER_READ_READY` poll into a static 32 KiB bounce buffer;
- the old per-sector path stays as a fallback: any non-`EBUSY` failure during
  the first CMD18 prints `CMD18 unavailable` and disables multi-block for the
  rest of the boot, so an unsupported controller costs one command, not a
  boot;
- on failure the CMD/DAT lines are reset (`SOFTWARE_RESET` 0x6) before the
  fallback retries, so a half-finished transfer cannot wedge the channel;
- `emmcstats=1` accumulates bytes/commands/time and prints
  `PRA eMMC: N KiB, M cmds, K KiB/s` every 8 MiB, so the gain is measured on
  the phone.

Expected effect: an 8-sector page-in becomes one command instead of eight, and
a 16-page cluster read one instead of 128. This matters more than core count
once the system starts paging in a 512 MiB window.

The other two limits, in order of payoff: the 512 MiB RAM window (jetsam and
page pressure) and cluster 1 (4 more cores), both still open.

### CI artifact was 62 MB for a 17 MB kernel

`xnu-kernel` uploaded all of `out/`, which includes
`kernel.development.pra.link` (135 MB on disk). The Mach-O alone is 17 MB and
zips to ~6.6 MB, but the artifact arrived at 61.7 MB.

- `xnu-kernel` now carries only `kernel.development.pra`,
  `…pra.lse.txt` and `SHA256SUMS`.
- `xnu-buildtree` (link tree + `kdk-libs`) is a separate artifact, kept 3
  days, and `tools/pra_ci.sh` downloads it only with `PRA_BUILDTREE=1`.
- Result: the default download is ~6.6 MB instead of ~62 MB. The raw p27
  image is still 17 MB because LK cannot decompress; that transfer is over
  adb (44 MB/s), not the internet.

## After the progress bar: text only, and services re-exec in a loop (2026-11-12)

Photo of the panel after the Apple logo + progress bar finished: the screen is
100% framebuffer console text, no GUI visible. The tail shows `exec xpcproxy`
interleaved with a small set of services repeating every few lines —
`fairplayd.H2`, `bluetoothd`, `usernetworkingd`, `CallDirectoryM`,
`CallReportingService`, `CallHistorySyncHelper`, `media` — plus
`SWEET FKS: securityd sel 10 arg0 0 in 2/32 out 1/40 -> 0xe00002c7`
(`kIOReturnUnsupported`) on every occurrence.

Two different readings, and this photo cannot separate them:

- **Console overdraw.** The framebuffer console scrolls, so after a few
  hundred lines it covers the whole panel no matter what CoreAnimation drew.
  Earlier boots showed GUI fragments *under* new text; a later photo only
  shows the newest text. GUI state is unobservable this way.
- **Crash-looping daemons.** `fairplayd.H2`, `bluetoothd` and
  `CallHistorySyncHelper` have no SEP, no Bluetooth controller and no
  telephony behind them here, so an immediate exit and OnDemand relaunch is
  plausible. Each relaunch is a fresh `exec` of a multi-MB Mach-O read over the
  polled SDHCI PIO path, on top of ReportCrash writing crash logs to disk; that
  would explain a good part of "mega slow" independently of block size.

Next image separates the two: `sweetfb_noconsole=1` stops the console drawing
the moment AppleCLCD first presents (a panic still draws, see
`serial_console.c`), and `pralog=1` keeps the log on p27 so a hang is still
recoverable from TWRP with `dd`. If a GUI appears the daemons are alive; if the
screen stays black the ring has the reason.

Caveat: with a present, muting `_cnputs` also stops feeding the 4 MiB ring, so
the disk log ends at the first present. That is the interesting boundary for
this test, but a later patch should append to the ring before the mute check so
post-GUI text survives too.

### RAM 512 MiB -> 1 GiB (a58f3f5)

`live/iomem.txt` has `87b08000-dfffffff : System RAM` as one contiguous range,
so the single `physBase`/`memSize` pair can grow from `0xa8000000` to
`0xc8000000`. Only two files define the window and both moved:
`tools/mkadt_pra.py` (`dram-size`) and `shim/pra/boot_main.c` (`RAM_END`); the
payload copies the ADT value, so nothing else had to change. The bootstrap
page tables already size for 2 GiB, and the real ceiling for one window stays
0xe0000000 (1.375 GiB).

Images built from CI kernel `42d4f1c8…` (0141 + 0142 + fixed linux gate),
`cpus=4`, `emmcstats=1`:

- `pra-xnu-smp4-raw.img` 1 GiB, console on — `ca81681e70b5a920…`
- `pra-xnu-1g-quiet-raw.img` 1 GiB, `sweetfb_noconsole=1 pralog=1` —
  `395702c5f19f4d66…`

Both write to p27 at LBA 753664 (368 MiB, `bs=1048576 seek=368`). The quiet
image clobbers the boot image with its ring and must be reflashed afterwards.

## mount(11) failed: the root block device never appeared (2026-11-12)

Boot of `pra-xnu-1g-quiet-raw.img` (`395702c5…`, 1 GiB + 0142 + `cpus=4` +
`emmcstats=1 sweetfb_noconsole=1 pralog=1`) ended with `mount(11) failed` on
the panel.

- That string is `IOKitBSDInit.cpp:703`, `IOLog("mount(%d) failed\n",
  mountAttempts)` behind a 5 s `IOSleep`. `mountAttempts` is post-incremented,
  so `11` is the **12th** attempt: mountroot retried for about a minute and
  never got a device. It is not an errno.
- p27's first sector still read `ANDROID!` afterwards, i.e. the `pralog=1`
  ring **never wrote a byte**, even though it flushes every 10 s.
- `pra_log_start()` is only called at the end of `pra_emmc_rootdev()`, after
  `pra_emmc_map_host()`, `pra_emmc_find_root_partition()` and the
  `bdevsw_add`/`devfs_make_node` calls. No log therefore means `rootdev`
  failed before line 1271 — the same failure that left mountroot without a
  device. 0140 could not log a failure in its own subsystem.
- Consequence: this is **not** the filesystem. A dirty HFS+ volume after the
  force-off would have failed *after* `pra_log_start()`, so there would be a
  log. The failure is in mapping the SDHCI host, reading the GPT, or
  registering the node.
- Verified against the live GPT: p27 `erecovery_kernel` starts at LBA 753664
  (368 MiB), 49152 sectors; the `dd seek=368` write lands exactly there and
  read back as `395702c5…`, so the image itself is where it should be.

### 0144: ring at the partition tail, started before the GPT

`0144-pra-log-early-and-tail.patch`:

- The ring target is now `first + sectors - PRA_LOG_SECTORS` = LBA 794623,
  which is 7,700 sectors past the end of the 33,220-sector image. Logging no
  longer destroys the next power-on, so a boot can be diagnosed and then
  simply repeated instead of reflashed.
- `praloglba=<LBA>` pins the target and starts the ring right after the host
  is mapped, before the GPT read, so a failure inside that read is captured.
  Without the boot arg the normal path is unchanged.
- `tools/pra_readlog.sh` dumps that ring over adb from TWRP and prints the
  newest text: `PRA_SERIAL=… tools/pra_readlog.sh` (default LBA 794623).

Between the last good boot (0141, 512 MiB) and this one only two things
changed: the 1 GiB window and 0142's CMD18 reads. The ring should name the
culprit on the next boot; no guessing.

## The mount loop was self-inflicted: a failed re-probe erased the geometry (2026-11-12)

`pralogat=60` dumped the in-memory tail on the panel and named the failure:

    hfs_mountfs: buf_meta_bread failed with 22
    hfs_mount: hfs_mountfs returned error=22 for device unknown-dev
    cannot mount root, errno = 19
    mount(12) failed
    PRA eMMC: card busy, skip read lba=1
    BSD root: sdhcroot0, major 1, minor 0
    PRA LOG: write failed 30 after 5 ticks

Reading it in order:

- `BSD root: sdhcroot0` means the GPT **did** parse and the block device
  exists. The earlier guess that rootdev never ran was wrong.
- `buf_meta_bread failed with 22` is EINVAL out of `pra_emmc_strategy`'s
  `off > bytes` check, i.e. the partition geometry was zero.
- `card busy, skip read lba=1` is the GPT header read (the only caller with
  absolute LBA 1), so `pra_emmc_find_root_partition()` was running again.
- `IOKitBSDInit` calls `pra_emmc_probe()` on **every** mount attempt, and
  `find_root_partition()` clears `pra_emmc_first_lba/nsectors` and the log
  target on entry. One transient EBUSY on that re-read therefore wiped a
  partition table the device had already parsed, and every later read
  returned EINVAL. The log target was wiped the same way, which is why the
  ring reported EROFS (30) and never landed.
- So mountroot was fighting a geometry that its own probe destroyed 12 times
  in a row. Nothing was wrong with HFS+ and nothing was wrong with the RAM.

### 0146: idempotent probe, non-destructive failure, emmcmulti=0

- `pra_emmc_probe()` returns at once once `pra_emmc_ready` is set.
- A failed parse restores the previous root **and** log geometry.
- `emmcmulti=0` turns off the CMD18 path at boot, so the still-unexplained
  "card busy" can be attributed to a multi-block transfer without a rebuild.

What made the card busy in the first place is not established yet. The
suspicion is a CMD18 that stops early (the per-block loop gives up) and is
aborted with a CMD/DAT reset but no CMD12, leaving the card mid-stream with
DAT asserted forever. `emmcmulti=0` is the experiment that settles it.

## SpringBoard is alive; the visible loop is five impossible daemons (2026-11-13)

Ring dumped from TWRP (LBA 794623, 253,341 bytes, not wrapped). The boot is
further along than the console made it look:

    hfs: mounted iOSRoot on device b(1, 0)
    exec launchd
    ...
    exec SpringBoard           (once)
    exec backboardd            (once)
    SWEET SURF: backboardd create id 2 1080x1920 fmt 0x42475241 bpe 4 bpr 4352 ...
    SWEET FB: swap 4 layer 0 surface 3 1080x1920 ... a 0,0 1080x1920 b 0,0 1080x1920

- `SpringBoard` and `backboardd` are each exec'd **exactly once**, so neither
  is respawning: the UI stack is up and backboardd is creating surfaces and
  swapping frames. The "Apple logo drowned in something opaque" is the kernel
  text console drawn over the GUI, not a display fault.
- `exec` counts over the whole boot: fairplayd.H2 182, bluetoothd 164,
  nanotimekitcompaniond 115, locationd 109, WirelessRadioManagerd 57. These
  cannot succeed on this phone (no SEP, no BT controller, no telephony, no
  GPS) and are the visible loop.
- `datamigrator`, `migrationpluginwrapper` and `Setup` exec'd several times:
  the first-boot migration is running, so the screen is expected to be the
  Setup Assistant rather than a home screen.
- `SWEET AKS: securityd sel 10 ... -> 0xe00002c7` and the same for
  SpringBoard: keybag operations we do not implement. Impact still unknown.
- Disk is the real drag: `PRA eMMC: 8212 KiB, 12976 cmds, 930 KiB/s`, with
  samples as low as 31 KiB/s. Every daemon exec re-reads a multi-MB Mach-O
  over single-sector PIO, which is why the loop looks frozen.

### TWRP cannot stage files: no HFS+ driver

`cat /proc/filesystems` in TWRP 3.5.2 lists no hfsplus and
`mount -t hfsplus` returns "No such device", so p58 cannot be mounted from
recovery. Staging has to be either a PC-side image edit plus a re-stage, or
an in-place overwrite of an already-allocated file (no HFS+ metadata work).

### 2026-11-13: the UI stack works; RunningBoard's launch watchdog is the blocker

Boot of `0148` + `emmcmulti=0` reached Setup Assistant and is the first boot
whose panel sequence is fully explained by the log (ring at LBA 794623,
91,675 bytes, seq 55, no panic, no `CRASH` other than the ones below).

Display, verified working end to end:

    SWEET FB: display on
    SWEET FB: swap 1 layer 0 surface 2 1080x1920 fmt 0x42475241 bpr 4352 ...
    SWEET FB: display off            <- boot screen ends, console muted here
    exec Setup
    SWEET FB: display on
    SWEET FB: swap 6 / 7 ...
    SWEET FB: display off

The Apple logo the user sees is drawn by userland (`IOMFB_FDR_Loader` ->
`backboardd`), not by a bootloader; there is no iBoot in this path. The logo
fading out is backboardd handing the display to the render server, which also
arms `sweetfb_noconsole` (mute happens at the first `present()`).

What actually stops the Hello screen:

    CRASH Setup[431] sig 9 ... reason ns 10 code 0x8badf00d:
      process-launch watchdog transgression:
      application<com.apple.purplebuddy>:431 exhausted real (wall clock)
      time allowance of 20.00 seconds
    CRASH chronod[473] ... reason ns 10 code 0x8badf00d:
      scene-create watchdog transgression: osservice<com.apple.chronod>:473
      exhausted real (wall clock) time allowance of 10.00 seconds

`exec Setup` appears three times: Setup Assistant launches, gets the display,
is killed at 20 s by RunningBoard, is relaunched. So the graphics path is no
longer the problem: the process cannot finish launching off this disk inside
the watchdog window. At the measured ~100 KiB/s the 20 s allowance is ~2 MB of
I/O, nowhere near what Buddy faults in.

Throughput shape (the reason it is that slow) - from the same ring:

    2142 2751 2738 2527 2757 2766 2747 2755 2376 2678 2547
    508  240  83   160  232  102  77   61   35   93   128  50 ...

Eleven 8 MiB windows at ~2.1-2.8 MB/s, then a collapse to tens of KiB/s that
begins at `exec backboardd`/`containermanagerd`, i.e. when first-boot starts
writing state. 512 bytes on a 26 MHz bus costs 157 us in transfer alone and
~185 us is measured, so **reads are already at the bus limit**: CMD18 could
not have bought more than ~15%, which retires it as a lever. The collapse is
on the write side (card program/erase time, HFS+ journal rewriting one region).

`emmcmulti=1` (0138/0148) is dead: it wedges the card before the first 10 s
flush, so the root read fails ("mount failed") and the ring cannot be written
at all - the ring stayed at seq 22, byte-identical. The CMD12 abort does not
rescue it. Not worth another boot.

Flashed but **not booted** (user asked to stop after the write):
`/tmp/opencode/pra/pra-xnu-0149.img`, sha256 `78ed044a...`, p27 LBA 753664.

    0147 exec skip + 0148 CMD12 (dormant, emmcmulti=0) + 0149 split stats
    emmcstats=1 emmcmulti=0 pralog=1 praloglba=794623 sweetfb_noconsole=1
    sweetfb_hz=1 praexecskip=fairplayd.H2,bluetoothd,nanotimekitcompaniond,
      locationd,WirelessRadioManagerd,rapportd,nsurlsessiond,cloudpaird,
      syncdefaultsd,chronod,ScreenTimeAgent,bluetoothuserd,nfcd,misd,
      mobiletimerd

0149 makes the stats line report reads and writes separately, plus the worst
single request and a `>5ms` count, and starts the ring before the first host
print so the SDHCI version/clock/capabilities survive a wedge. That tells us
whether the collapse is write time (uniformly slow writes) or a hot spot (a
few very slow requests, e.g. the HFS+ journal).

Next levers, in order of expected value:

1. Read the 0149 `(r ... | w ...)` numbers to confirm the write collapse.
2. Raise the bus clock: high-speed mode (CMD6 SWITCH HS_TIMING=1, 52 MHz) is a
   clean 2x on every read and is the only safe lever on the read side.
3. If the split shows a journal hot spot: disable HFS+ journaling on the p58
   working copy offline (dump -> edit -> write back), which also removes the
   biggest write amplifier.
4. Only then consider disabling RunningBoard's launch watchdog, or the
   SetupDone bypass the user does not want yet - the Hello screen should be
   reachable by speed alone, since Setup does run and does get the display.

### Handoff 2026-11-13 (stopping for the day)

State at stop: `pra-xnu-0149.img` is flashed to p27 and the phone was rebooted
into it by the user; whether it finished booting is unknown. The phone is in
**XNU**, not TWRP. To get back: force off, then vol+ + power with the cable
unplugged. The ring at LBA 794623 then holds the 0149 boot.

Saved to persistent disk (research/ is gitignored):

    research/p58-20261113.img        10,271,850,600 B, full p58 after a first boot
    research/pra-artifacts/ring5.txt 91,675 B ring - the Setup/watchdog boot
    research/pra-artifacts/ring{2,3,4}.txt, ring.txt
    research/pra-artifacts/pra-xnu-0149.img    what is flashed now (78ed044a...)
    research/pra-artifacts/pra-xnu-single-raw.img  0148 with emmcmulti=0
    out/ci.0147 out/ci.0148 out/ci.0149           CI kernels (sha256sums inside)
    ~/Videos/Moskau/                 Moskau-1080p.mp4, moskau-full-480p.mp4

`/tmp` is a 16 GiB tmpfs and does not survive a reboot, which is why the ring
logs and both flashed images were copied out. The video originals, the 60 s
cuts and `art140/` were left in /tmp on purpose.

First thing next session - read the 0149 ring and compare the split:

    PRA eMMC: 8192 KiB, ... KiB/s (r ... KiB ... cmds ... KiB/s | w ... KiB
      ... cmds ... KiB/s | >5ms N max N us)

Then `host base=... clock=... caps=... base=N MHz div=N`, which is now inside
the ring because 0149 moved `pra_log_start()` ahead of the first print.

Decision tree from those two lines is in the section above: uniform slow writes
=> write volume / block size; few very slow requests => HFS+ journal hot spot.

## GPU: what the herolte branch proves, and what it costs here (2026-11-13)

The user pointed at `wardevsa/ios-a5xelte` branch `herolte`: a Galaxy S7
(SM-G930F, Exynos 8890, Mali-T880 MP12) that reaches the iPhone X iOS 16.7.16
home screen with the GPU doing CoreAnimation. A shallow clone is in
`research/herolte-ref` (6.2 MB, gitignored).

How that stack is built, because it decides what transfers:

- `iokit/Kernel/arm/HeroGPU.cpp` (grown from `bsd/dev/herolte_gpu.c`, patches
  0225-0250 and 0333): an XNU-internal Midgard driver - probe, page tables,
  job slots and fences, tiler heap, BO alloc/map/submit, IOSurface import -
  exposed to userland as one IOKit user client. Not kbase, not DRM.
- `gpu/mesa/herodrm.c` + `build-mesa.sh` + `patch-mesa.py`: a libdrm stand-in
  that answers Mesa's panfrost DRM ioctls with that IOKit client, and Mesa
  25.0.7's Panfrost + OSMesa cross-built for iOS arm64 (`iphoneos` SDK).
- `gpu/eagl` (Bergamota's EAGL shim) and `gpu/hakios-gl` (HakiOS EAGL bridge
  with CoreAnimation hooks): SpringBoard/backboardd keep calling EAGL/GL ES,
  which lands in OSMesa -> Panfrost -> our kernel jobs. Patches 0245/0246 put
  the shim in the root and widen AMFI/dyld policy so it loads.

Why this is closer to possible here than it looks: the PRA's GPU is a Mali-T830
MP2, and T830 is the same Midgard **v5** ISA as the T880. Mesa's Midgard
compiler, descriptor layout and most quirk handling are shared, and Panfrost
already lists 0x830. The kernel driver's Exynos constants are the part that
does not transfer.

Hardware facts for hi6250, from Huawei's own GPL DTS in
`/home/kamion008/Ai/huawei/hi6250-kernel`
(`arch/arm64/boot/dts/auto-generate/config/hi6250/hisi_6250_gpu.dtsi`):

    gpu: mali@E8970000   reg 0x4000, compatible "arm,malit6xx","arm,mali-midgard"
    interrupts: 258 JOB, 259 MMU, 260 GPU (SPI, level)
    clocks = <&clk_g3d>;  gpu-supply = <&g3d>;
    OPP: 120 MHz 696 mV, 240/698, 360/700, 480/744, 680/820, 800/943, 900/1073

The best news is in `hisi_6250_powerip.dtsi` and `hisi_6250_clock.dtsi`: on
hi6250 the GPU rail and clock are **not** PMIC/CRG register pokes, they are two
LPM3 IPC requests that the vendor firmware already implements -

    g3d enable  0x00030004 / disable 0x00030104   (regulator "g3d", type2)
    clk_g3d set-rate 0x0003030A, get-rate 0x0003020A, devid 2

So power-on + rate is a mailbox conversation with LPM3, not the Exynos-style
BUCK4 voltage table plus CMU divider/mux sequencing that cost herolte the
0130/0170 patches. The mailbox message format is in Huawei's full kernel
release (our local tree is a DTS-only cut, no `drivers/`), and the LPM3 side is
still alive under our kernel - it is what the stock boot chain talks to.

Stage order stays the herolte one: probe (expect GPU_ID product 0x830) ->
one private WRITE_VALUE job -> fragment clear -> IOSurface import -> panel
blit -> user client -> Mesa/OSMesa -> EAGL shim in SpringBoard.

Two honest costs:

- This is stage 4 of 4. It cannot put the Hello screen on the panel; the eMMC
  throughput and the 20 s launch watchdog do that. It makes the UI usable
  afterwards, and it is untestable until boot and touch work.
- The userland side is not free either: OSMesa+Panfrost+shim are ~20 MB that
  every first boot must read from a 0.5 MB/s eMMC (~40 s), so it interacts
  with the I/O problem rather than sidestepping it.

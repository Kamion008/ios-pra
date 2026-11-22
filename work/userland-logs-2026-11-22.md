# PRA-LX1 userland logs on the eMMC iOS root (read-only forensics)

Date: 2026-11-22. Device: the device, booted to TWRP (recovery), root adb.
Scope: read-only. Nothing was written, mounted read-write, flashed or pushed.
All host scratch work lived in `/tmp/pra-forensics/` (outside the repo).

## Verdict (short)

Userland-side evidence of the HID path **exists**, contrary to the assumption that
the userland had never logged anything. The eMMC iOS root holds real unified-log
archives and a real `launchd.log` written by the iOS 16.7.16 userland during the
PRA boots, and they contain the backboardd HID service, SpringBoard's digitizer
stream client, and the display/digitizer power gating state.

Read together, the records show the HID plumbing is present and matched end to
end (backboardd owns a `BKIOHIDService` for the SweetHID touch device, SpringBoard
has a `BKDigitizerStreamClient` for system gestures) while the delivery gate is
closed: the same archive carries records with `digitizerEnabled: NO`, `display:
off` / `backboardd` display-power "score" reasons involving `backlight-off +
pocketTouches`, and a digitizer rect of `{{0,0},{1,1}}`. A `BKIOHIDService` record
for the touch device reports `events:0`. No backboardd or SpringBoard crash is
recorded, and neither process ever exited.

Caveat that bounds every quote below: the `.tracev3` payload is lz4-chunked
(`bv41` chunk tag) and the strings are OSLog *dictionary* entries, so `strings`
recovers authentic short fragments in file order, not complete log lines. The
fragments are quoted verbatim with byte offsets; they are evidence of what the
userland logged, but they are not full sentences and carry no per-line timestamps.
Turning them into exact lines needs a real tracev3 decoder, which was out of scope
here.

## 1. Which partition is the iOS root, and in what format

`/proc/partitions` and the by-name links (TWRP):

    adb -s "$PRA_SERIAL" shell 'cat /proc/partitions'
    adb -s "$PRA_SERIAL" shell 'ls -l /dev/block/bootdevice/by-name/'

    userdata -> /dev/block/mmcblk0p58      14340096 KiB  (13.67 GiB logical)

Corroborated by the repo tooling:

- `tools/pra_package.sh`: the proven cmdline carries `rd=sdhcroot0 emmcroot=userdata`
  (block comment at the top explains each arg; `rootrw=1` is part of the default).
- `tools/pra-stage-iosroot.sh`: writes a PC-side image to
  `/dev/block/bootdevice/by-name/userdata`, expects `14340096 KiB`, streams over
  adb stdin, and warns it erases Android user data on `mmcblk0p58`.
- `tools/mkiosroot.sh`: `mkfs.hfsplus -s -J -v iOSRoot` -- "case-sensitive
  journaled HFS+", mounted on the build host with `-o loop,force`, hence the
  `tools/pra_hfs_journal.py` / `tools/pra_hfs_watchdog.py` helpers.

Volume header read straight off the partition (block 0, offset 1024), no mount:

    adb -s "$PRA_SERIAL" exec-out dd if=/dev/block/mmcblk0p58 bs=4096 count=1024 > p58-head.bin

    sig HX  ver 5  attributes 0x80002000  lastMountedVersion HFSJ  journalInfoBlock 0x6f
    fileCount 182501  folderCount 135610  blockSize 4096  totalBlocks 3585024
    freeBlocks 1021767  nextCatalogID 0x53042
    catalog file: logical 161480704 B, 39424 blocks, 14 extents (fragmented)
    extents file: 1280 blocks @2160   attributes: 2816 blocks @3440
    allocation:   110 blocks @1      startup: empty

`HX` = HFSX, i.e. case-sensitive HFS+; `HFSJ` is the journaled last-mounter tag;
the journaled attribute bit `0x2000` is set. So the root is exactly what
`mkiosroot.sh` builds, and it is the live root the kernel used with
`emmcroot=userdata`.

## 2. Mount attempt: blocked, with the exact error

TWRP's kernel has no HFS+ driver at all:

    adb -s "$PRA_SERIAL" shell 'cat /proc/filesystems'
      -> ext3 ext2 ext4 squashfs vfat msdos exfat ecryptfs sdcardfs cifs
         fuseblk fuse fusectl overlay f2fs  (+ nodev pseudo filesystems)

    adb -s "$PRA_SERIAL" shell 'grep -i hfs /proc/filesystems'
      -> squashfs        (substring match only; no hfsplus, no hfs)

    adb -s "$PRA_SERIAL" shell 'mkdir -p /tmp/iosro; mount -t hfsplus -o ro /dev/block/mmcblk0p58 /tmp/iosro'
      -> mount: '/dev/block/mmcblk0p58'->'/tmp/iosro': No such device     (rc=1)

    adb -s "$PRA_SERIAL" shell 'mount -t hfs -o ro /dev/block/mmcblk0p58 /tmp/iosro'
      -> mount: '/dev/block/mmcblk0p58'->'/tmp/iosro': No such device     (rc=1)

`No such device` is ENODEV (filesystem type not registered in the kernel), not
EBUSY, so this is "no driver", not "already mounted". There is no module
directory to load one from (`/system/lib/modules`, `/lib/modules`: nothing HFS).
TWRP is toybox-only (`blkid`, `mount`, `dd` from toybox). Therefore step 3 of the
brief (mount and walk) was impossible on the device and mounting was never done.

Two toybox quirks that matter for anyone repeating this:

- `dd bs=1M` fails: `dd: block size '1M': illegal number`. Use `bs=4096`.
- toybox `dd` writes its statistics line to **stdout**, after the data, so a naive
  `exec-out dd ... > file` yields data plus a trailing stats blob (e.g. 4183 bytes
  for 4096 requested). Read exactly `count*bs` leading bytes and discard the rest.

## 3. Fallback: block-level HFSX reader on the host (no mount, no writes)

Since the format was confirmed from the volume header, the volume was read
block-wise: a small reader (`/tmp/pra-forensics/hfsx.py`, host-side, ~350 lines)
parses the volume header, resolves each fork's extents (using the extents-overflow
B-tree for the 9th+ extents), and walks the catalog B-tree with HFSX binary key
comparison. Only the blocks actually needed are fetched, into a sparse local cache:

    adb -s "$PRA_SERIAL" exec-out dd if=/dev/block/mmcblk0p58 bs=4096 skip=<blk> count=<n>

Cache footprint: 35 MB physical in a sparse 10.7 GB file. Total device reads for
the whole investigation: see the per-step "adb calls" counts (a few hundred 4-8 KiB
reads; roughly 60 MB transferred). Nothing was read twice and no bulk 14 GB copy
was done.

Sanity checks that the parse is correct: the catalog file's extents resolve to
exactly 39424 blocks (8 inline + 6 overflow), `fileCount/folderCount` match the
volume header, and the root directory lists a plausible iOS 16 root
(`System`, `usr`, `private`, `Library`, `Applications`, `bin`, `sbin`, `cores`,
`.journal`, `.hotfiles.btree`, ...).

## 4. What is on the volume: inventory

Everything below was enumerated through the catalog, then pulled by extents.

| tree | entries | notes |
|---|---|---|
| `/private/var/db/diagnostics/Persist` | 51 `.tracev3` | unified log, persisted; ~4 KB to 10.5 MB each |
| `/private/var/db/diagnostics/Special` | 35 `.tracev3` | special/rapid log; 220 KB to 1.2 MB each |
| `/private/var/db/diagnostics` | `.migrated`, `HighVolume/`, `Signpost/` | |
| `/private/var/log` | 4 files + `asl/`, `mDNSResponder/`, `ppp/` | the only plain-text logs |
| `/private/var/mobile/Library/Logs` | 110 entries | CrashReporter stack is IPSW sample data only |
| `/private/var/db/DiagnosticPipeline` | absent | not created on this root |
| `/private/var/db/lockdown` | 0 entries | |
| `/private/var/root/Library/Lockdown` | `data_ark.plist` (173 B) | no host pairing records |

Plain-text logs (the highest information density per byte):

| size | path |
|---|---|
| 1549029 | `/private/var/log/com.apple.xpc.launchd/launchd.log` |
| 2176236 | `/private/var/log/com.apple.xpc.launchd/launchd.log.1` |
| 2036169 | `/private/var/log/com.apple.xpc.launchd/launchd.log.2` |
| 375 | `/private/var/log/com.apple.xpc.launchd/launchd_cache_loader.log` |
| 1910 | `/private/var/mobile/Library/Logs/AppleSupport/general.log` |

Unified-log archives pulled and examined:

| size | path |
|---|---|
| 10436472 | `/private/var/db/diagnostics/Persist/0000000000000001.tracev3` |
| 10415280 | `/private/var/db/diagnostics/Persist/0000000000000025.tracev3` |
| 6809384 | `/private/var/db/diagnostics/Persist/0000000000000026.tracev3` |
| 1184432 | `/private/var/db/diagnostics/Special/0000000000000001.tracev3` |
| 1023952 | `/private/var/db/diagnostics/Special/0000000000000017.tracev3` |

Keyword census over those five archives (`strings -a FILE | grep -c`): only
`Persist/0000000000000001.tracev3` carries the HID material (`backboardd` 10,
`SweetHID` 5, `digitizer` 3, `HIDEvent` 2, `gesture` 4, `dropped` 11).
`Persist/...25` and `...26` are dominated by other subsystems and returned zero
hits for all HID keywords; the two `Special` archives carry only subsystem-name
level mentions (`backboardd` 2, `BKSHID` 1, `gesture` 1).

The three `launchd.log` files are three consecutive boots (one `hello` banner
each), and their `boot-args` records distinguish them:

- `launchd.log.2`, `launchd.log.1`: `... sweetsample=Setup ...`
- `launchd.log` (newest): `... sweetsample=SpringBoard,backboardd ... pratouch=1
  pratouchreset=1 pratouchdbg=1 pratouchselftest=1 prapowerkey=300`

so the newest boot is the touch-experiment boot, and it ran for about 13.5 minutes
of userland time (first record 16:00:43, last 16:14:14; the RTC is unset, so all
timestamps are the 1969/1970 epoch plus uptime).

## 5. Excerpts

Quotes are verbatim byte sequences from `strings -a`, in file order; `|` marks a
string boundary inserted by extraction, `?` marks a byte replaced by the
extractor. Offsets are decimal and hex.

**E1. backboardd owns a matched BKIOHIDService for the SweetHID touch device, and
its event counter reads 0.**
`/private/var/db/diagnostics/Persist/0000000000000001.tracev3` @3761035 (0x39638b):

    {GraphicsOrienta | : 1}
    <BKIOHIDService: 0x149f23e30; s
    Status: matched; 3
     name:SweetHIDTouch id:0x10 | 12a primaryUsagePage:0xd | :0x4 transport:SPU re
    Interval:0 b | 1 events:0 mask:0x | anderID | 012A; displayUU | "0;< | @Sour | builtin;
    J 0xD | 4; authenticated: YES;G

Reading: service status `matched`, name `SweetHIDTouch`, registry id `0x10000012a`,
`primaryUsagePage:0xd` (digitizer), `usage:0x4` (touch screen), `transport:SPU`,
source `builtin`, `authenticated: YES`, and the counter field before `events:`
reads `0`. Same id `0x10000012a` recurs in E2.

**E2. SpringBoard's digitizer stream client exists (system gestures), on the same
device id.**
Same file @3761420 (0x39650c):

    <BKDigitizer? | StreamClientq | +14b063c50; pid: 26(v45); SpringBoard; system-gestures; cre
    ationTime: 2396.0215; ...
    aDestin! | Q: <BKz | Qf0; (5 | |filterDeta | es); context
    ... 0x6203>; val | 2YES | Mode: igno | ; ambiguityRecommend | unspecified>

Reading: a `BKDigitizerStreamClient`/event-processor for `pid: 26` `SpringBoard`
with the `system-gestures` filter, creation time 2396.02 (uptime seconds), and
filter details ending in `Mode: ignore; ambiguityRecommendation: unspecified`.
The SpringBoard side of the delivery path is therefore registered and alive; the
client is not the missing piece.

**E3. The delivery gate: display off, digitizer disabled, pocket-touch gating.**
Same file @4106616 (0x3ea978):

    : SB + backlight-off + pocketTouches; | ximityDet | pMode: l' | d;
    digitizerEnabled: NO | Psplay | e: off; multitW | AHost | Keys: (WakeOnTapC | A)>
    56(vD2); | baseline | standar | `YES> | `AutoBrA

Reading: a backboardd/CoreBrightness display-power record whose reason list is
`SB + backlight-off + pocketTouches`, with `digitizerEnabled: NO` and `display:
off`, plus `WakeOnTap` host keys. `vD2` is backboardd (pid 56). The complementary
record at @4465860 (0x4424c4) has the opposite state:

    <score: 1; vpid: 56(vD2); back | d; reason: | baseline + pocketTouchesEnabled(SB
    ... | standard; digitizerW | k: YES; ... | O: on

i.e. a CoreBrightness "score: 1" explanation for backboardd, `reason: baseline +
pocketTouchesEnabled(SB...)`, `digitizerWake: YES`, display `on`. Both states are
attributed to the HID/display gating logic, not to the touch device.

**E4. Degenerate digitizer geometry next to a 1080x1920 display.**
Same file @189147 (0x2e2db):

    indow^'#er | :0x149f10c30 s | scale:3 na | ;1Rot | p:0 norm
    edDigitizerRect:{{0,0},{1,1}} exJ-d:0
    <CAr | LCD primary>

Reading: a `CAWindowServer`/display dictionary for an `LCD primary` display with
bounds `{1080, 1920}` (stated earlier in the same run) and a digitizer rect of
`{{0,0},{1,1}}`. A 1x1 digitizer rect makes every hit test land in a single unit
square; this is the most direct userland-side candidate for "events are consumed
but never dispatched".

**E5. The boot args and the process lifecycle, in plain text.**
`/private/var/log/com.apple.xpc.launchd/launchd.log`, line 4 and lines 288-294,
766-771, 946-948:

    1969-12-31 16:00:43.490152 <Notice>: boot-args = debug=0xc serial=3 cpus=4
      keepsyms=1 rd=sdhcroot0 emmcroot=userdata emmcprobe=1 emmcwrite=1 rootrw=1
      unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1
      wdt_test=no_user_checkin wdt=-1 emmcstats=1 pralog=1 praloglba=794623
      sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1 sweetfb_hz=1
      sweetsample=SpringBoard,backboardd praexecskip=locationd,... pratouch=1
      pratouchreset=1 pratouchdbg=1 pratouchselftest=1 prapowerkey=300

    1969-12-31 16:01:10.838648 (user/501/com.apple.SpringBoard) <Notice>: internal event: WILL_SPAWN, code = 0
    1969-12-31 16:01:11.096106 (user/501/com.apple.SpringBoard [26]) <Notice>: service spawned with pid 26
    1969-12-31 16:01:11.096325 (user/501/com.apple.SpringBoard [26]) <Notice>: Successfully spawned SpringBoard[26] because system support
    1969-12-31 16:01:10.955591 (user/501/com.apple.backboardd) <Notice>: internal event: WILL_SPAWN, code = 0
    1969-12-31 16:01:10.959481 (user/501/com.apple.backboardd [56]) <Notice>: xpcproxy spawned with pid 56
    1969-12-31 16:01:16.106520 (user/501/com.apple.backboardd [56]) <Notice>: Successfully spawned backboardd[56] because speculative

Both daemons spawn and reach `running`; grep for `exit`, `kill`, `signal`,
`terminat`, `crash`, `invalidat` on `pid/26 [SpringBoard]` / `pid/56 [backboardd]`
returns nothing, and SpringBoard is still creating XPC service stubs at
16:10:39, ~9.5 minutes after spawn. So SpringBoard is running but idle, and
backboardd is running with no crash. The same log ends at 16:14:14 on an unrelated
`locationd` respawn loop (note `praexecskip` lists `locationd`, yet it respawns).

**E6. Persisted backboardd digitizer state.**
`/private/var/mobile/Library/Preferences/com.apple.backboardd.plist` (175 B):

    {'BKDigitizerPersistentServiceProperties': [
        {'props': {'GraphicsOrientation': 1},
         'sender': {'display': '<builtin>', 'page': 13}}]}

Reading: backboardd persisted a digitizer sender identified by `page: 13` (0x0d)
on display `<builtin>`, with orientation 1. The device *is* bound to the builtin
display as a page-13 sensor, which again says the service identity is right.

## 6. Persisted UI state (the lock-screen question)

| size | path | content |
|---|---|---|
| 179 | `.../Preferences/com.apple.SetupDone.plist` | empty dictionary `{}` |
| 42 | `.../Preferences/com.apple.SpringBoard.plist` | empty dictionary `{}` |
| 1915 | `.../Preferences/com.apple.springboard.plist` | 18 keys |
| 175 | `.../Preferences/com.apple.backboardd.plist` | see E6 |

The interesting part is the pair of case-differing files. `com.apple.SetupDone.plist`
and `com.apple.SpringBoard.plist` are both empty, while the all-lowercase
`com.apple.springboard.plist` holds real state:

    SBLastSystemVersion = '20H392'      SBFWebClipUtilitiesLastSanitizedBuildVersionUserDefaultsKey = '20H392'
    BKNoWatchdogs = True                SBLastRestoreIdentifier = '3BB28404-B02B-41AA-A208-EB0014E8DD47'
    SBRecentLocale = 'en-US'            SBRingerMuted = False
    SBButtonForceFeel = 2               SBSwitcherBottomEdgeGestureSwipeCount = 2
    SBHomeScreenWallpapers / SBLockScreenWallpapers   FBLaunchWatchdogExceptions = {'com.apple.purplebuddy': 100.0}
    SBShouldAddDefaultWidgetsToHomeScreen = False     SBShouldResetDefaultTodayList = False

On a real iOS device `/private/var` is case-insensitive, so
`com.apple.SpringBoard.plist` and `com.apple.springboard.plist` are one file; on
this case-sensitive HFSX root they are two. Preference state can therefore be
written by one component and read by another that spells the name differently, and
`com.apple.SetupDone.plist` being an empty dictionary means no setup-complete keys
were recorded on this root. Together with `com.apple.purplebuddy` carrying a
watchdog exception, the persisted state is consistent with the device still being
treated as not set up, which is one way to remain parked on the lock/setup UI
regardless of touch input.

Note the absence of the usual "first boot" evidence: `/private/var/db/lockdown` is
empty, there are no host pairing records, and the whole CrashReporter tree contains
only the IPSW's baked-in sample reports (all dated 1969-12-31, e.g.
`PosterBoard-1969-12-31-161304.0002.ips`). No crash report was generated by
backboardd or SpringBoard during these boots.

## 7. Answer to the open question

Is there userland-side evidence of the HID path? Yes.

- Present: the digitizer is matched as a HID service (`BKIOHIDService` matched,
  `SweetHIDTouch`, page 0x0d usage 0x4, `builtin`, `authenticated: YES`), backboardd
  persisted its sender (`page: 13`, `<builtin>`), SpringBoard created a digitizer
  stream client for `system-gestures`, the display server knows the panel
  (`LCD primary`, 1080x1920), and both daemons run without crashing for the whole
  boot.
- Also present, and pointing at the blockage: a digitizer rect of `{{0,0},{1,1}}`;
  records where `digitizerEnabled: NO` accompanies `display: off` with the reason
  `SB + backlight-off + pocketTouches`; the mirrored "display on, digitizerWake:
  YES" record for the same process; and an `events:0` counter on the touch
  `BKIOHIDService`. That is a delivery gate closed at the *display state / geometry*
  layer rather than a missing device or a dead client.
- Absent, and why: no `IOHIDFamily` kernel-trace lines and no full `BKSHID` event
  dispatch lines. Those live in the lz4-compressed `bv41` payload of the
  `.tracev3` archives, and only dictionary fragments survive `strings`. `/private/var/db/DiagnosticPipeline`
  does not exist on this root, and `IOHIDEventSystemConnection` records that did
  surface belong to other processes (`PosterBoard`, pid 1648), not to the
  digitizer delivery to SpringBoard.

Concrete next step that would settle it: decode one `.tracev3` properly (OSLog
catalog + `bv41` lz4 chunks) instead of `strings`, filtered on subsystem
`com.apple.backboardd` / `com.apple.iohid`, and on the SweetHID service id
`0x10000012a`. The archive to decode is `Persist/0000000000000001.tracev3`, whose
raw bytes are already cached on the host.

## 8. Reproducing this read

    export PRA_SERIAL=<serial>
    adb -s "$PRA_SERIAL" shell 'cat /proc/partitions'
    adb -s "$PRA_SERIAL" shell 'ls -l /dev/block/bootdevice/by-name/'
    adb -s "$PRA_SERIAL" exec-out dd if=/dev/block/mmcblk0p58 bs=4096 count=1024 > p58-head.bin   # volume header
    adb -s "$PRA_SERIAL" shell 'grep -i hfs /proc/filesystems'                                    # no hfsplus
    adb -s "$PRA_SERIAL" shell 'mkdir -p /tmp/iosro; mount -t hfsplus -o ro /dev/block/mmcblk0p58 /tmp/iosro'
    # -> ENODEV; then block-wise reads only:
    adb -s "$PRA_SERIAL" exec-out dd if=/dev/block/mmcblk0p58 bs=4096 skip=<blk> count=<n>
    strings -a 0000000000000001.tracev3 > p1.strings
    grep -n -i 'sweethid\|hidEvent\|digitizer\|dropped\|backboardd' p1.strings
    grep -abo -- '<BKIOHIDService: 0x149f23e30' 0000000000000001.tracev3
    dd if=0000000000000001.tracev3 bs=1 skip=3760900 count=430 | strings -a -n 3

Device was left untouched: no writes, no mount, no reboot, no fastboot, no push.

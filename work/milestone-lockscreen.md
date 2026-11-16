# MILESTONE — iOS lock screen reached on PRA-LX1 (2026-11-16, ~21:36)

Photo: research/pra-artifacts/lockscreen-2026-11-16.jpg (2.4 MB, uncommitted
dir). The iOS 16.7.16 lock screen ("Wednesday, December 31, 4:08", unlock
grabber at the bottom, rdar:45025538 status-bar placeholder) rendered by
SpringBoard on the phone, CPU-only.

## What was on the phone for this boot

- Kernel: 0175 (out/pra-xnu-0175-blr.img sha 29512a04…, CI 43958048368
  SUCCESS) — the diagnostics-only kernel: th/st/we/wq/cont/blr/kbt per
  thread; NO behavioral fix. The wedge simply did not reproduce this time
  (timing-sensitive; rings 30/31/32 wedged at different depths).
- Root: the tweaked image (research/iosroot/ios16-root-v12.img after tools/
  sweet-root-tweaks.py) — the fixes that mattered, in order of likelihood:
  1. launchd.plist job fixes (7x _PanicOnCrash->_PanicOnCrasX, 2 CommCenter
     jobs removed) — the churn source was System/Library/xpc/launchd.plist,
     NOT the LaunchDaemons files earlier sessions removed.
  2. /private/var/containers/{Bundle,Data/System,Shared/SystemGroup,Temp}.
  3. The real purplebuddy Setup bypass (SetupDone/SetupFinishedAllSteps/
     SetupVersion 11, daemonizeNeedsToRun off, mini-buddies off) — Setup's
     wizard no longer runs (ring32 verified: 0 PRA MSG records).
  4. SpringBoard BKNoWatchdogs, migration prefs (DataMigration skipped),
     VirtualAudio/MediaToolbox recorder fixes.
- DataMigration and the Setup wizard were the two big early-boot write
  storms; the launchd sync()/mkdirat UNINT wedge (rings 31/32) hit during
  them. ring33 (on disk at LBA 794623, NOT yet pulled at the time of this
  note) holds the healthy boot's rings: whether the wedge fired at all, and
  the blr/kbt chains if it did.

## Open items after the milestone (next session)

- Pull ring33 BEFORE the next boot (it is the healthy-boot baseline).
- Touch: 0172's CYTT21403 probe is read-only I2C; touch input is not wired
  to IOKit/HID - the unlock bar will not respond yet. Wiring input is the
  next feature milestone (then unlock -> home screen).
- The wall clock is wrong (Dec 31 1969-era; no RTC) - cosmetic for the lock
  screen, matters later.
- The wedge root cause is still unnamed - ring33's blr/kbt chains (0175)
  may name it even in the healthy boot (near-miss blocks), and the
  fairplayd.H2/bluetoothd/nanotimekitcompaniond jobs still churn in
  launchd.plist (donor script removes only CommCenter).
- 0175 is on master with CI green; the assert fix commit (0173 marker) is
  also on master.

## Second sighting (2026-11-16, later) — CORRECTED

Another boot of the same image reached the lock screen — that is 2 of the
last 3 boots. CORRECTION (the first version of this note was wrong): the
"8:59" was the user's stopwatch timing of the boot, NOT the clock. The
lock screen's clock is FROZEN at 4:08 across boots AND across re-renders
(swaps went to 15 in ring34's boot while the clock stayed 4:08):
mach_absolute_time advances (timers, sampler cadence work) but the WALL
CLOCK does not — the timebase->gettimeofday conversion is broken or zero.
Next-session item, elevated: fix the kernel wall clock (check the ADT
timebase 1.92 MHz vs the real CNTFRQ, the clock.c scale, and the boot
epoch seed). The ring34's black-screen boot remains the one wedged on
_pra_emmc_lock (stochastic).

# Working on the A5XELTE fork

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
debug=0xc serial=3 cpus=4 keepsyms=1 rd=sdhcroot0 emmcroot=userdata emmcprobe=1 emmcwrite=1 rootrw=1 unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 emmcstats=1 emmcmulti=0 pralog=1 praloglba=794623 sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1 sweetfb_hz=1 sweetsample=Setup praexecskip=locationd,WirelessRadioManagerd,fairplayd.H2,bluetoothd,nanotimekitcompaniond,CommCenter
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
- **`sweetfb_noconsole=1 a5fb_noconsole=1 a5fb_keep_on=1 sweetfb_hz=1 sweetsample=Setup praexecskip=locationd,WirelessRadioManagerd,fairplayd.H2,bluetoothd,nanotimekitcompaniond,CommCenter`** —
  framebuffer console keep-alive (the on-screen capture path).
- **`unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1`** —
  boot progress args from the working boots; do not prune.

The old trap: `pra_package.sh` used to default to `cpus=1 … -noprogress`, and
hand-written CMDLINE overrides kept losing args (the 2026-11-13 handoff command
block itself had a lossy short version — the 2026-11-14 boot failed on the phone
because of it). The default is now the proven string and both scripts gate on it.
Do not weaken the gates.


- For Samsung SM-A510F work, read `A5XELTE_PROGRESS.md` and `docs/a5xelte-migration-map.md` first. Record new device evidence in the former and commit completed changes. Keep private VM addresses, passwords, device dumps and downloaded Apple binaries out of git.
- Preserve recovery p11, EFS p3 and the existing Linux BOOT checkpoint. Current XNU trials may write only the explicitly authorized BOOT p10; the donor's Xiaomi `fastboot` and USERDATA instructions are not A5XELTE instructions.
- Keep build success, recovered kernel markers, physical screen reports and iOS runtime behavior as separate claims. `NOTES.md` below is SWEET donor history; do not edit it to imply Samsung behavior.

## Original SWEET contributor instructions (donor reference)

- Read `NOTES.md` before starting; it contains the project goal, hardware facts,
  current blocker, local artifact locations and the next concrete action.
- The user switches agents frequently. Update the active handoff in `NOTES.md`
  after each milestone and before stopping. Record commits, CI run IDs, exact
  build/boot results and unfinished work. Distinguish observations from guesses.
- Commit completed changes. Use `gh` for GitHub Actions kernel builds and logs.
  Local single-file cross-compiles are useful before spending a CI run.
- Device bring-up uses temporary `fastboot boot` images. Preserve the Android
  installation and partition backups. The user approved (2026-10-15) using
  internal UFS for iOS and said Android may be deleted: the iOS root goes
  into the existing `userdata` partition (no GPT changes). Keep bootloaders,
  recovery, modem, persist and the backups intact, and confirm each
  destructive step with the user before running it.
- Keep device dumps, serial numbers and downloaded Apple artifacts out of git.

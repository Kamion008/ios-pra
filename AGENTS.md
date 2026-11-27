# AGENTS.md — ios-pra (PRA-LX1 iOS port)

## Project
Goal: boot the iPhone X iOS 16.7.16 userland on a Huawei PRA-LX1 (Kirin 655 /
hi6250) via the Android boot image → EL1 loader (`shim/pra`) → a ported XNU
(xnu-8796.141.3). Donor tree: `ios-galaxy-s8` (SWEET/A5XELTE).
READ FIRST: the latest `HANDOFF_*.md` (currently `HANDOFF_2026-11-23d.md`, written
  after the ring64 + tracev3 causality evidence - wake re-enables the digitizer -
  and self-contained) — the
single source of truth for status, verified facts, refuted theories and the
do-not-do list. This file holds stable mechanics only.

## Repo layout
- `PRA-LX1_PROGRESS.md` — PRA-specific evidence log (hardware facts, boot history).
- `HANDOFF_2026-11-23d.md` — active handoff (causality answered: a wake event re-enables the digitizer;
  0201 packaged, awaiting flash); `HANDOFF_2026-11-22c.md` and `HANDOFF_2026-11-22b.md` are superseded.
  Add newer dated ones after it.
- `NOTES.md`, `A5XELTE_PROGRESS.md`, `docs/` — donor history; inherited claims
  there (fastboot boot, BOOT p10, 12-arg gate, sweetsample=Setup) are STALE.
- `xnu/patches/` — the numbered patch stack (`NNNN-*.patch` + stager `.sh`).
- `tools/` — `pra_ci.sh` (dispatch macOS CI), `pra_package.sh`, `pra_flash_skip.sh`,
  `pra_readlog.sh` (ring pull), `mkiosroot.sh` (root staging), `mkadt_pra.py` (ADT).
- `shim/pra/` — EL1 loader + `build-xnu.sh`; `work/` — per-session notes/rings/scripts.
- `research/`, `live/`, `out/`, `xnu-src/`, `backup/` — gitignored artifacts.

## Build / package / flash / log
- Build: CI only (no local macOS toolchain): `RUNNER=macos-15 tools/pra_ci.sh Kamion008/ios-pra`;
  fetch a kernel with `gh run download <run-id> -R Kamion008/ios-pra -n xnu-kernel`.
- Package: `bash tools/pra_package.sh <kernel.development.pra>` → `out/pra-xnu.img`.
- Flash: `PRA_SERIAL="$PRA_SERIAL" bash tools/pra_flash_skip.sh out/<img>.img`
  — writes ONLY p27 (erecovery_kernel) via adb dd, then verifies a readback sha.
- Ring log: `tools/pra_readlog.sh` (or `adb exec-out dd if=/dev/block/mmcblk0
  bs=512 skip=794623 count=8193`, then `strings -a`). ALWAYS `cmp` against the
  previous ring first (wraps leave stale content); /tmp is volatile — copy into `work/`.

## The boot cmdline
The canonical cmdline is the DEFAULT inside `tools/pra_package.sh` — do not copy
it into docs (it drifts; AGENTS.md went stale that way before). Both
`pra_package.sh` and `pra_flash_skip.sh` hard-refuse any image missing the 11
critical args: cpus=4 rd=sdhcroot0 emmcroot=userdata emmcprobe=1 emmcwrite=1
rootrw=1 emmcstats=1 pralog=1 praloglba=794623 wdt=-1 wdt_test=no_user_checkin.
Experiments append args via the CMDLINE env WITHOUT pruning defaults; only
`PRA_ALLOW_ANY_CMDLINE=1` bypasses the gate (deliberate one-offs).

## Patch hygiene
CI runs the three stage `.sh` scripts, then applies every patch in order; a
patch whose `git apply` fails is skipped SILENTLY, so `.github/workflows/xnu.yml`
asserts one marker string per landed patch (`grep -F`). Every new patch adds a
marker assert and is verified with the 0164 method: stage scripts + `git apply`
of the whole stack (zero skips), then GNU `patch -p1 --fuzz=0 --dry-run` on
index-stripped diffs. Local `git apply --check` proves nothing (git 2.56
skip-detects already-applied patches with rc=0). Never trust a green CI without
checking the asserts.

## Arithmetic (scripts/calculators, never mental math)
Every calculation that lands anywhere durable — a claim, a boots.md
row, a patch header/comment, a handoff entry, a decode: address
arithmetic, shifts/masks, byte/sector/KiB conversions, counts, rates,
base conversions — is computed with a script or calculator
(`python3 -c …`, bc) and the tool output is quoted beside the result
as the anchor. Mental arithmetic in prose is how the 13<<23 and the
155.0-KiB slips happened (both caught by review rounds; both
preventable). If a review round refutes arithmetic, the fix quotes
the recomputed tool output, not a new hand calculation.

## Safety (the handoff do-not-do list is authoritative)
- Flash only p27 via `pra_flash_skip.sh` — never p30/p32, bootloaders, recovery,
  modem, persist, EFS, BOOT. Battery ≥25%; force-flash only on explicit approval.
- Never boot without `pralog=1 praloglba=794623` (a blind boot loses evidence).
- Serials via PRA_SERIAL env only — never in git. No Apple binaries, device
  dumps or personal data in git.
- Get explicit user approval (exact command shown first) before any flash, restage or destructive eMMC write.
- Keep build success, on-screen reports and runtime behavior as separate claims;
  label evidence VERIFIED (file:line/command) vs INFERRED vs UNKNOWN.

## iOSOnAnd tracker

This port's per-phone status is on the iOSOnAnd tracker
(https://hackios.appaiproxy.com/device/huawei-p8-lite-2017), repo
Kamion008/ios-pra, phone huawei-p8-lite-2017. Follow the `iosonand-tracker`
skill (`.claude/skills/iosonand-tracker/SKILL.md`; latest at
https://hackios.appaiproxy.com/SKILL.md):

- keep `cli.mjs` outside the repo (`~/.local/share/iosonand/cli.mjs`) and
  read/verify its sha256 before running;
- ask the user once how tracker updates and release posts should go (`auto`,
  `ask`, `off` in `~/.config/iosonand/agent-prefs.json`) and update after a
  phone boot or release as they chose — this repo's saved preference: updates
  `auto` unless a boot kernel panics before loading userspace; release posts
  `ask`;
- always ask and show the file and caption before uploading any image or video
  (`--photo`, `media-upload`, `update` with files), even when updates are set
  to `auto`;
- never include personal data, vendor files or keys, and only claim what a log,
  capture or pushed doc shows.

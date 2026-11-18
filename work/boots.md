# Boot series — the wedge acceptance test (protocol in HANDOFF_2026-11-16-c.md §6.3)

Series order (decided 2026-11-17, before start): baseline = 0175 kernel
(no telemetry), SECOND series = 0176 (telemetry + fix). The baseline is its
OWN series — NEVER pooled with the post-0176 series. SAME kernel + SAME root
per series, no mid-series changes; kernel sha recorded per row. Failure
procedure: a wedged boot -> pull the ring from TWRP BEFORE the next boot.
Predictions discipline starts at boot #3 (work/predictions-2026-11-17.md):
boots 1-2 are UNPREDICTED. Baseline started 15:58:14.

| # | kernel/root | reached lock screen | uptime at photos | wedge telemetry | clock reading | ring pulled |
|---|---|---|---|---|---|---|
| (pre-series reference) | 0175+tweaks | y (milestone, ~6 min, photo) | 4:08 | — | 4:08 frozen | ring33 |
| (pre-series reference) | 0175+tweaks | n (black, wedge) | — | we=_pra_emmc_lock+0x8, launchd+backboardd UNINT | 4:08 frozen | ring34 |

(Reference rows above are pre-series context, not part of the series.)

## BASELINE series (kernel 0175 + tweaked root — FROZEN build, started 2026-11-17 15:58)

| # | kernel sha | reached | boot time | uptime at photos | wedge telemetry | clock | ring | pred |
|---|---|---|---|---|---|---|---|---|
| 1 | 29512a04dba33d8a5281 | **y** | 8m30s | 4:08 @ ~10 min; 4:08 @ ~15 min | — (healthy) | 4:08 at two uptimes — H2 coincidence branch refuted; FROZEN vs NEVER-REDRAWN stays OPEN until the clock_get_calendar_microtime sampler line lands in a ring | ring35 (sha 9316b9ce; cmp-vs-34 diverges byte 17 = boot #1 wrote) | unpredicted |
| 2 | 29512a04dba33d8a5281 | **y** | not separately timed (user: "same as boot 1, no changes") | — | — (healthy) | 4:08 (implied by "no changes") | ring36 (sha 9316b9ce) — **BYTE-IDENTICAL to ring35: boot #2 wrote NOTHING in the ring window (anomaly → predictions P5; after-window probe = ANDROID! magic, no ring space past it)** | unpredicted |
| 3 | 29512a04dba33d8a5281 | **y** (user: "same as boot 2") | ~8-9 min class (not separately timed) | — | — (healthy) | 4:08 (implied by "same as boot 2") | ring37 sha 9316b9ce — **BYTE-IDENTICAL to ring35 AGAIN (cmp empty, header seq still 9): boots #2 AND #3 wrote NOTHING to the disk ring; P5 upgraded from one-off to pattern (2/3 healthy boots stale)** | predicted |
| 4 | 29512a04dba33d8a5281 | **y** (user: "WORKED") | shorter than #1-#3 (user: "probably booted in less time") | — | — (healthy) | **4:07** — the label VARIES with boot duration (4:08 in #1-#3, 4:07 here): epoch+uptime at render time, advancing; NEVER-REDRAWN now leads H2 (frozen-gettimeofday refuted by 4:07≠4:08 across boots; no advance within boot #1) — 0176 sampler header line confirms in-ring per protocol | ring38 sha 9316b9ce — **IDENTICAL to ring35 AGAIN (seq stuck at 9): P5 now 3 of 4 healthy boots wrote ZERO bytes** | predicted |
| 5 | 29512a04dba33d8a5281 | **y** (user: "AGAIN, 4:07 in lock screen") | ~8m class | — | — (healthy) | **4:07** (2nd consecutive) | ring39 sha bb29d0ef — **DIFFERS: boot #5 WROTE (header seq=2, total=133,205)** — starvation spectrum across healthy boots: 0 / 0 / 0 / 2 / 9 successful flushes of ~90 ticks; parks resolve (th= 0x9→0x1→0x9 timeline) | predicted |
| 6 | 29512a04dba33d8a5281 | **y** (user: "last boot was 4:08") | ~8m class | — | — (healthy) | **4:08** (render-time variance within the class) | ring40 sha bb29d0ef — **IDENTICAL to ring39: boot #6 also wrote ZERO** — spectrum now 9/0/0/0/2/0 successes of ~90 ticks (near-total starvation; the 0176 fix predicts near-full success — built-in validation) | predicted |

SERIES DECISION (2026-11-17, user: "run the new kernel"): the baseline series
STOPS at boot #6 — 6/6 healthy (+ the pre-series milestone boot = 7 of the
last 8). The ~1/3 wedge rate is not reproduced; the mechanism is audited
(work/audit-pra-emmc-lock-2026-11-17.md). The 0176 series (telemetry + fix)
starts next: same frozen-build rules, kernel 0176, rows below.

## 0176 series (kernel 0176 + same tweaked root — FROZEN build)

| # | kernel sha | reached | boot time | wedge telemetry | clock | ring | pred |
|---|---|---|---|---|---|---|---|
| 1 | 4f26e5674eb65eeb (image; kernel 12bfcf29a91f6374c564, CI 44190353269) | **VOIDED — IO-starved by the flush storm** (user: strat flushes "every 0.1 s"; ring41: 9,404 strat-flush lines, consecutive 128-block flushes 62 bytes of log apart — the %128-sector gate + force=true made the storm self-sustaining; fixed in e2e160e) | — | — | — | ring41 sha ae5177a1 (banked — the bug's primary evidence) | predicted (T1-T3) |
| 2 | 7203d89a4ad35d65 (image, readback-verified; kernel 64e3da879ca46a23cd56, CI 44197699736 — the request-count flush fix) | interrupted at ~10 min by the touch reflash; console: storm reduced ~5x (user estimate) | — | — | — | ring42 = boot T's ring (boot 2's own ring was overwritten by the touch boot before pulling) | predicted (T1-T3) |
| T2 | f276ef64ae6983b7 (the touch-variant image — the accidental stale-package flash; kernel 64e3da87 + the pratouch args) | **n — failed to reach the lock screen; terminal state = the launchd spawn-churn loop** (NOT the mutex wedge: 0 parks at the mutex, the flusher healthy seq=48, 937 strat flushes, 33 write-fails; the lock-state dump FIRED: data=000d24b5 wakeup=0 owner=0xfffffff54bb35000 — a RUNNING holder, never sampled = fork-(a)-consistent, not stuck) | — | the churn: 1,248 exec-xpcproxy lines (vs 119 in ring41's window — 10x); the touch ladder = the same rung-A failure (the window bug — 0178 pending in CI) | n/a (no lock screen) | ring43 sha 910a4f63 (the wedge telemetry's first live fire) | predicted |
| T | f276ef64ae6983b7 (image, readback-verified; SAME kernel 64e3da87, cmdline variant: default + `pratouch=1 pratouchreset=1`, CI 44197699736) | **y**, 11 min, no touch (expected — the ladder failed at rung A) | 4:09 (variance data) | — | — | **FIX VALIDATED (ring42, fresh region = 18,056 B): 103 strat flushes (ring41 storm: 9,404 — 91x down); the periodic flusher: seq=1 + ONE write-fail (healthy — the starvation is GONE); (lock=) attribution live x1; cal= absent = expected (the sampler prints per park event, quiet boot)**. TOUCH: pratouchreset=1 reached the driver; **reset gpio18.1 assert readback FAILED (dat=0)** → BL_LAUNCH_APP correctly skipped → desc NACK unchanged. NEXT: PRA's real GPIO18 bank address (0xE8A1D000 is donor-derived — wrong for PRA) | predicted (T1-T3 + the design-note ladder) |
| T3 | 080654d9249139cf (image, readback-verified; kernel 2d71ed5df7f6c86d = the 00bec18 tree with the 0178 DAT-window+bit fixes, CI 44339538567's kernel) | **y** (the lock screen per user; touch not working as expected), ~11 min class, 4:09-class clock implied | — | **THE CHURN TERMINAL FAILURE AGAIN** (1,207 exec lines; the flusher healthy: 955 strat flushes, 32 write-fails — the flush fix holds; the 0179 AKS fix = the churn's next step) | 4:09-class | ring44 sha 622df9fa. **THE TOUCH LADDER: RUNG A PASSED** ("reset gpio18.1 done dir=2 dat=0" — the 0178 window+bit fix CONFIRMED on hardware) → the failure MOVED to the bus: **BL_LAUNCH_APP write failed err=6 (address NACK)** → the rails (VCI=LDO17/VDDIO=LDO4) = the prime suspect; the rail-offset research dispatched | predicted (the design-note ladder) |

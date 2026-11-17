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
| 6 | 29512a04dba33d8a5281 | **y** (user: "last boot was 4:08") | ~8m class | — | — (healthy) | **4:08** (render-time variance within the class) | ring40 pending (phone in XNU at last check — pull on TWRP return) | predicted |

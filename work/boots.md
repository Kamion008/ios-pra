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
| 3 | 29512a04dba33d8a5281 | fired 17:03:34, outcome pending (user checks screen) | — | — | — | — | ring37 after TWRP return — also the P5 discriminator (did boot #3 write?) | predicted (predictions-2026-11-17.md, committed pre-boot) |

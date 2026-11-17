# Boot series — the wedge acceptance test (protocol in HANDOFF_2026-11-16-c.md §6.3)

Series: TBD (start after 0176 lands; SAME kernel + SAME root for every row,
no mid-series changes). Failure procedure: a wedged boot -> pull the ring
from TWRP BEFORE the next boot. Baseline decision: whether to also run a
no-telemetry series (0175 kernel) — decide before starting.

| # | kernel/root | reached lock screen | uptime at photos | wedge telemetry | clock reading | ring pulled |
|---|---|---|---|---|---|---|
| (pre-series reference) | 0175+tweaks | y (milestone, ~6 min, photo) | 4:08 | — | 4:08 frozen | ring33 |
| (pre-series reference) | 0175+tweaks | n (black, wedge) | — | we=_pra_emmc_lock+0x8, launchd+backboardd UNINT | 4:08 frozen | ring34 |

(Reference rows above are pre-series context, not part of the series.)

## BASELINE series (kernel 0175 + tweaked root — FROZEN build, started 2026-11-17 15:58)

| # | reached | boot time | uptime at photos | wedge telemetry | clock | ring |
|---|---|---|---|---|---|---|
| 1 | **y** | 8m30s | photo 1 pending (~10 min) | — (healthy) | pending 2-photo test | pending |

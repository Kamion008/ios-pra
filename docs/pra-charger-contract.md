# PRA charger contract — hi6250 charging + battery reporting

One driver, one patch, one agent. This file is the contract: what to build,
which files may change, and which writes are forbidden. If something here is
not enough to decide, stop and report the question instead of guessing.

## 1. What is being built

- Driver: **PRA charger** — bring up the I2C charger IC and report state to
  iOS through `SweetBattery`.
- Purpose: let the phone charge while XNU runs, and stop iOS from claiming
  "100%, AC, not charging" from a hardcoded fallback.
- Patch number and slug: **`0143-pra-charger.patch`**. `0141`/`0142` are taken.
- Existing tree: `xnu-src/` already has `0139` (SDHCI root), `0140` (console
  ring) and `0142` (multi-block reads) applied. The patch must apply on top.

## 2. Hardware facts (from the live device, do not re-derive)

- Charger IC: **TI BQ25892** — `CONFIG_BQ25892_CHARGER=y`,
  `CONFIG_HISI_CHARGER=y`, `CONFIG_SCHARGER_V200=y`,
  `CONFIG_SCHARGER_V300=y` in `live/kernel-config.txt`. It is an I2C part;
  mainline `bq25890_charger.c` is the register reference. Confirm the 7-bit
  address from that driver (0x6B on this family) instead of guessing.
- I2C controllers (DesignWare, polled, no interrupts needed):
  - `0xFFD73000`, reset register `0xFFD7E000`, `cs-gpios 187,188`,
    input clock 19.2 MHz, 64-entry FIFOs. `live/dmesg.txt:892-907`.
  - `0xFDF0D000`, reset register `0xFFF35000`, `cs-gpios 37,38`,
    input clock 120 MHz. `live/dmesg.txt:909-924`.
  Which one carries the charger is **not** established. Probe both, read-only.
- PMIC: HI6555 at `0xFFF34000` (`live/iomem.txt:103`). Battery profile on this
  unit is `SCUDATL`; the coulomb counter reports FCC 2657 mAh, OCV 4.34 V,
  97.8% SOC at the sampled boot (`live/dmesg.txt:687-715`). The gauge itself
  is out of scope for this patch.
- Battery: 3000 mAh nominal. `SweetBattery` already uses `SWEET_BAT_MAH 3000`
  for the PRA build.
- The bootloader has its own charger firmware. I2C pinmux and the bus may
  already be usable at XNU handoff; do not reconfigure pinmux.

## 3. Safety rules (non-negotiable)

- **Never write** VREG (float voltage), JEITA thresholds, termination,
  BATFET, boost/OTG, or anything that changes the battery's charge profile.
  A wrong write can overcharge or overheat the battery.
- Allowed writes, and only behind `pracharger=1`:
  - `EN_HIZ = 0` (leave high-impedance mode),
  - input current limit ≤ 500 mA,
  - fast-charge current ≤ 512 mA,
  - watchdog: disable it or set the longest period, and if enabled, kick it
    from the poll thread.
- Default is **read-only**: probe, log status, publish state, never write.
  With `pracharger=0` or absent, not one write may reach the chip.
- Before any write: the chip must answer with a plausible status register
  (`REG0B`) and no fault bits in `REG0C`. Otherwise log once and stay
  read-only.
- Every write path must be bounded: polled loops with iteration limits, no
  sleeping while holding a lock, no `panic()` on any failure.
- If the chip does not respond at either address on either controller, that is
  a normal outcome: log `PRA charger: no charger found` and return.

## 4. IOKit shape

- BSD-style driver like `bsd/dev/pra_sdhci.c` is acceptable for the I2C
  engine, but the published state must reach `SweetBattery`.
- Concretely:
  - `bsd/dev/pra_charger.c` — new file: DW I2C read/write (polled), BQ25892
    probe on both controllers/addresses, status decode, 10 s poll thread
    (`kernel_thread_start`, like the SDHCI log thread), and
    `int pra_charger_status(unsigned *percent, unsigned *mv, int *ma,
    int *external, int *charging, int *full);` returning 0 when the chip is
    present and 1 when it is not (so the caller keeps its fallback).
  - `iokit/Kernel/arm/SweetBattery.cpp` — PRA path only: replace the stub
    `dreamlte_battery_read()` with a forward to `pra_charger_status()`, keep
    the static fallback when it returns non-zero. Do not touch the DREAMLTE
    or SWEET paths.
  - `bsd/conf/files` — add the source, `optional iokitcpp`-style like the
    other PRA entries.
- Driver start order: must not delay boot. Probe once, cheaply; if the bus
  does not move, give up rather than spin.
- Boot args: `pracharger=1` enables writes, `prachgdebug=1` logs every
  register access.

## 5. Percent reporting

Do not invent a fuel gauge. With a BQ25892 and no coulomb counter, derive
percent from `VBAT` with a flat Li-ion OCV table (3.30 V = 0%, 4.35 V = 100%,
monotonic), clamp 0..100, and mark it as an estimate in the log. `mv`, `ma`,
`external`, `charging` and `full` come from the chip's status/ADC registers.
`full` is true when `CHRG_STAT == 3` (charge done). If the ADC is not
converted, request one conversion (REG0E) and re-read; never busy-wait longer
than ~20 ms.

## 6. Verification

- The patch must apply cleanly: `git apply --check` on a copy of `xnu-src`
  with 0139/0140/0142 applied (that is the current tree, so check forward on
  a `-R`-reconstructed copy or state exactly which tree it applies to).
- Compile evidence: `tools/xnu-cc.py` single-file compile if it can express
  this file; otherwise state clearly that CI is the first compile and list
  every include and symbol you are unsure about.
- Report: what you wrote, what you could not establish (bus/address, clock
  gating, pinmux), and the exact boot-arg combination the main agent should
  try first. Do not flash, do not boot, do not edit progress docs, do not
  push, do not renumber other patches.

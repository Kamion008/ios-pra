# Stock touch bring-up reverse-engineering — 2026-11-19 (read-only)

## 1. Answer

The complete GPL stock bring-up chain for the PRA touch IC (Cypress TT5 "CYTT21403"
on the 0xFFD73000 DW host) is now anchored file:line from the huawei-oss dump, and
the stock-vs-port diff has THREE confirmed hardware deltas our port never performs,
one of which exactly produces the observed "clean bit-0 abort at every address":

- **DELTA 1 (top candidate): the reset-gpio final level + pulse polarity.** The
  stock kernel drives gpio145 (gpio18.1) as **idle = PHYSICAL HIGH** and pulses it
  **LOW for 40 ms** as the reset (`gpio_set_value(rst,1)` 20 ms → `0` 40 ms → `1`
  100 ms, plat:235-249), and init drives `gpio_direction_output(rst_gpio, 1)`
  immediately after the rails come up (plat:284). Our port does the inverse —
  HIGH 10 ms then **leaves the line LOW forever** (pra_touch.c:1247-1259) — i.e.
  if XRES is active-low (which the vendor sequence on THIS hardware asserts), our
  port **holds the IC in hardware reset through the scan and every transaction**,
  which is precisely the electrical signature of "no ACK at any address on a
  verified-live controller". Mainline's "asserted HIGH" (cyttsp5.c:874 `GPIOD_OUT_HIGH`,
  ml:874) is a *logical* gpiod assertion whose PHYSICAL level comes from the DT
  active-low flag our port doesn't have; both mainline (with the flag) and the
  vendor (raw gpio) agree the physical reset state is LOW, idle HIGH.
- **DELTA 2: the LDO VSET selectors are never written by our port.** Stock writes
  the voltage selectors on every power-up: LDO17 (VCI) vset reg **0x4E ← 2
  (2.80 V)** and LDO4 (VDDIO) vset reg **0x42 ← 3 (1.80 V)** via
  `regulator_set_voltage` (core:6955/:6964 → regu:196-198, tables pmicdtsi:70-73,
  165-168), and only then enables bit 0 of the onoff regs 0x25/0x19 (regu:133-135)
  — the only part our port does (pra_touch.c:1152-1159). If the PMIC reset/boot
  default for either selector is not the touch voltage, the IC is "enabled" but
  under/over-powered → silent.
- **DELTA 3: the IOMCU reset pulse.** Stock pulses the i2c2 IP reset (write
  BIT(5)→0xFFD7E020, poll bit5@0xFFD7E028, write BIT(5)→0xFFD7E024, poll clear;
  hisi:139-153, tuple i2cdtsi:30-31) at probe (hisi:966), at resume (hisi:1136),
  and after EVERY fifo-wedge/timeout (forkcore:772-773, 799-800). Our port never
  touches the window.
- Also confirmed as stock-but-probably-innocuous deltas: SPKLEN=1 / SDA_HOLD=38 /
  TX_TL=RX_TL=15 / FS+HS HCNT-LCNT / INTR_MASK=0 writes (forkcore:437-456, 988),
  CON=0x65 FAST@400k with HCNT=112/LCNT=204 (our port: CON=0x63 STD@100k,
  512/768), per-transfer pinctrl default↔idle toggling + per-transfer clk
  enable/disable (forkcore:732/:739/:859/:861 — no hardware gate on this bus, the
  sibling i2c report already proved clk_gate_i2c2 is a fixed-factor clock), the
  `retries=3` core layer, the SCL-recovery trick (TAR=0x7f + one read + 100 ms,
  hisi:690-727), and — important for the post-ACK world — the vendor wire form is
  **write-STOP then SEPARATE pure reads, never repeated start** (i2cbus:252-288),
  while our descriptor read uses wr+repeated-start (pra_touch.c:651-662).
- The stock kernel's FIRST I2C transaction is a **1-byte pure read at 0x1C** in
  `cyttsp5_detect` (xres → 100 ms → read ×3, plat:352-358), and the live PRA stock
  dmesg shows it SUCCEEDED with no retry print (xres done 20.442s, irq setup
  20.554s, no "Read unsuccessful" between; live/dmesg.txt:4052-4109) — the IC
  ACKed ~280 ms after rails-on on a bus configured exactly as below.
- The pull-up encoding question is answered DEFINITIVELY: the 0xFFF11800 cfg
  register **bit 0 = pull-up enable, bit 1 = pull-down enable** (decoding in
  section 3c); the stock net cfg value for gpio187/188 is **0** (all four dts
  tuples clear their bits) — identical to the cfg=0 our port already reads
  (claim-0183.md:23-25) ⇒ **pinconf/bias is NOT the dead-bus delta; the bus
  pull-ups are external on the board**.

## 2. Access method / anchor chain

- Fetched GPL sources (all VERIFIED, saved durably under
  /home/kamion008/Ai/ios/ios-pra/work/rvr/, mirror layout; repo
  github.com/hisi-oss/android_kernel_huawei_hi6250-8 branch lineage-20):
  - `rvr/i2c/hisi_i2c_designware.c` (the "i2c_designware-hs" platform driver; cited **hisi:NNN**)
  - `rvr/i2c/i2c-designware-core.c` + `.h` (the shared core, CONFIG_HISI_I2C_DESIGNWARE=y,
    merge_hi6250_defconfig:348-349; cited **forkcore:NNN**/**forkhdr:NNN**)
  - `rvr/pinctrl/pinctrl-single.c` (**ps:NNN**)
  - `rvr/cyttsp5/cyttsp5_core.c|_i2c.c|_platform.c|_devtree.c|_regs.h` (the vendor
    cyttsp5 stack under drivers/huawei_platform/touthscreen/panel/cyttsp5/ — note
    the Huawei directory typo "touthscreen"; cited **core/i2cbus/plat/devtree/regs:NNN**)
  - `rvr/regulator/hisi_regulator.c` (**regu:NNN**), `rvr/mfd/hisi_pmic.c` (**pmic:NNN**),
    `rvr/include_mfd/hisi_pmic.h`
  - `rvr/dts/{hisi_6250_i2c.dtsi,hi6250_udp_default_config.dtsi,hi6250_udp_default_pin.dtsi,
    hisi_6250_pinctrl.dtsi,hisi_6555v100_pmic.dtsi,merge_hi6250_defconfig}` (**i2cdtsi/udp/pin/pmicdtsi:NNN**)
  - `rvr/mainline/cyttsp5.c` (torvalds master; **ml:NNN**) for the reset-polarity cross-check.
- The PRA product dts is NOT in the dump (only UDP/emulator/fpga configs exist —
  repo-tree grep); but the live stock PRA dmesg
  (/home/kamion008/Ai/ios/ios-pra/live/dmesg.txt) pins the PRA-specific values:
  chip CYTT21403 / irq 224 / rst 145 / hid_desc_register 1 / dtz+gesture values
  byte-identical to the UDP node (dmesg.txt:3894 vs udp:519-522, 498) — so the
  UDP nodes + vendor code ARE the PRA stock path modulo the product dts.
- Local: work/ci183/post0182/xnu/bsd/dev/pra_touch.c (**pra:NNN** — note the
  0183 scan patch referenced by claim-0183 is not in this post0182 copy; the
  scan's behavior is taken from claim-0183.md), work/claim-0182.md,
  work/claim-0183.md, sibling reports work/i2c-research-2026-11-18.md,
  work/gpio18-research-2026-11-18.md.

## 3. The stock bring-up path, ordered (power-on → first ACKed transaction)

### 3a. i2c2 host probe — hs_dw_i2c_probe (hisi:810-1055); ran at 19.361s (dmesg:892-907)

1. `ioremap(0xFFD73000)` (hisi:853, no request_mem_region) + `devm_ioremap`
   of the reset window `reset-reg-base = <0xFFD7E000 0x1000>` (hisi:860-866;
   i2cdtsi:30).
2. dts parse: `reset-controller-reg = <0x20 0x24 0x28 5>` (hisi:875-879 →
   priv{enable_off=0x20, disable_off=0x24, status_off=0x28, bit=5}, hisi:890-893;
   i2cdtsi:31); `delay-off = 300` (i2cdtsi:29); cs-gpios 187/188 for recovery
   only (hisi:881-887; dmesg:896 prints the PRA values 187/188); clk "clk_i2c"
   (hisi:899); `clock-rate` → clk_set_rate (hisi:903-913; PRA dmesg:897 prints
   19200000 but clk_get_rate still returns 128 MHz, dmesg:902-903 — the fixed
   parent wins, sibling report sec 4); speed-mode missing → `DW_IC_CON_SPEED_FAST`
   (hisi:915-918, forkhdr:33 = 0x4); retries 3 / timeout 100 (hisi:927-941).
3. `clk_prepare_enable` (hisi:943-947) — no-op gate on this bus (fixed-factor).
4. **`hs_i2c_dw_reset_controller`** (hisi:126-156, called at hisi:966): assert =
   `writel(BIT(5), 0xFFD7E000+0x20)`; poll bit5 of +0x28 ≤ 10 µs until SET;
   deassert = `writel(BIT(5), +0x24)`; poll bit5 until CLEAR (hisi:139-153).
5. Read `COMP_PARAM_1` (0xF4) → depths 64/64 (hisi:968-975; dmesg:901).
6. `i2c_dw_init` (forkcore:338-467, called hisi:984) — EVERY register write, in
   order (values computed for ic_clk=128000 kHz, formulas forkcore:253-307;
   script-checked):
   - COMP_TYPE verify 0x44570140 (forkcore:356-369).
   - `__i2c_dw_enable(false)`: ENABLE(0x6C)=0 + ENABLE_STATUS(0x9C) poll, 100
     tries (forkcore:309-328, :372).
   - SS_SCL_HCNT(0x14)=**547**, SS_SCL_LCNT(0x18)=**639** (forkcore:380-395;
     `i2c_dw_scl_hcnt(128000, 4000, 300, 0, 0)`, `lcnt(…, 4700, 300)`) — the
     hisi probe never sets dev->ss/fs/hs hcnt (grep: only sda_hold_time set,
     hisi:979-982), so the computed values are what ran.
   - FS_SCL_HCNT(0x1C)=**112**, FS_SCL_LCNT(0x20)=**204** (forkcore:399-415).
   - HISI-guarded HS_SCL_HCNT(0x24)=**48**, HS_SCL_LCNT(0x28)=**63**
     (forkcore:417-435; CONFIG_HISI_I2C_DESIGNWARE=y, defconfig:349).
   - **IC_FS_SPKLEN(0xA0)=1, IC_HS_SPKLEN(0xA4)=1** (forkcore:437-439).
   - **SDA_HOLD(0x7C)=38** — `(128000 kHz * 300 ns)/1e6` (hisi:979-982 default
     delay-off=300; version check forkcore:442-450; 0x3132302a ≥ 0x3131312A).
   - **TX_TL(0x3C)=15, RX_TL(0x38)=15** (forkcore:452-455).
   - DMA_TDLR(0x8C)=tx_depth−16=48, DMA_RDLR(0x90)=15 (forkcore:456 → hisi:498-502;
     CONFIG_DMA_ENGINE in the shipped build — dmesg:906 "no TX DMA channel!" is a
     print that only exists under it, hisi:219).
   - CON(0x00)=master_cfg = MASTER|SLAVE_DIS|RESTART_EN|SPEED_FAST = **0x65**
     (hisi:961-962 → forkcore:462).
   - NOTE: i2c_dw_init leaves the controller DISABLED; it never enables at probe.
7. `i2c_dw_disable_int`: INTR_MASK(0x30)=0 (hisi:988 → forkcore:1134-1137).
8. IRQ (GIC 120, i2cdtsi:23) request (hisi:990-1007), recovery info from
   cs-gpios (hisi:1009-1024), `i2c_add_numbered_adapter` (hisi:1030), DMA probe
   (hisi:1043), **`clk_disable`** (hisi:1045) — the clock is off between transfers.

### 3b. Per-transfer mechanics — i2c_dw_xfer HISI path (forkcore:716-872)

1. mutex, **clk_enable** (forkcore:732), **pinctrl "default"** = mux 187/188 to
   func 0x1 (forkcore:739; states at udp:432-433).
2. `i2c_dw_wait_bus_not_busy`: poll STATUS(0x70) & ACTIVITY(0x1), 20 ms budget
   (forkcore:473-487, :761).
3. `i2c_dw_xfer_init` (forkcore:489-533): ENABLE=0+poll; CON read-modify-write
   (10-bit bit clear for 7-bit); **TAR(0x04)=addr every transfer**;
   INTR_MASK=0; ENABLE=1+poll; CLR_INTR read; INTR_MASK=TX_ABRT|STOP_DET
   (forkcore:528-529).
4. **FIFO-wedge gate**: if STATUS&(TX_OVER|RX_FULL) ≠ 0 OR TXFLR&0x3f ≠ 0 OR
   RXFLR&0x3f ≠ 0 → `reset_i2c_controller` = pinctrl idle → **IOMCU reset pulse**
   → full i2c_dw_init → INTR_MASK=0 → pinctrl default (forkcore:768-776 →
   hisi:160-185) → -EAGAIN.
5. Push DATA_CMD: STOP=bit9 on the last byte of the last msg; **the RESTART bit10
   is deliberately NOT set** (forkcore:604-611 "no need to set this bit" — with
   IC_RESTART_EN the HW inserts the repeated start); reads queued as `cmd|0x100`
   (forkcore:619). DMA only if total ≥ tx_fifo_depth=64 (hisi:575-576) — touch
   frames are PIO.
6. Completion via IRQ (forkcore:787). Timeout path: wait for the ISR to drain,
   then **IOMCU reset pulse + full re-init** (forkcore:799-800); the final
   -ETIMEDOUT ALSO triggers `hisi_dw_i2c_scl_recover_bus`: pinctrl idle,
   ENABLE=0, CON=0x43, TAR=0x7f, ENABLE=1, DATA_CMD=0x100, msleep(100),
   pinctrl default, i2c_dw_init (forkcore:846-857 → hisi:690-727) — the stock
   9-clock un-wedge. `retries=3` at the core layer re-runs the whole xfer on
   -EAGAIN.
7. On TX_ABRT: ISR captures TX_ABRT_SOURCE BEFORE the CLR_TX_ABRT read
   (forkcore:1005-1011, the 0181 lesson, stock-authored).
8. **clk_disable** (forkcore:859), **pinctrl "idle"** = 187/188 back to func 0x0
   (forkcore:861; pin:717-719/724-726) after EVERY transfer.

### 3c. pinctrl-single 4-cell tuple semantics (ps) → the gpio187/188 cfg word

Parse: `pcs_add_conf4` reads `<value enable disable mask>` (ps:1040-1063), each
ANDed with mask (ps:1055-1057), `pcs_config_match(value, enable, disable)` → 1
(enable) / 0 (disable) becomes the packed setting arg (ps:990-1000, :1058-1062).
Set: `pcs_pinconf_set` reads the pin's cfg register (offset = pin*4, ps:654-655),
then per param: 2-cell params (drive-strength/slew-rate) clear the mask field and
OR `(arg << ffs(mask)-1) & mask` (ps:659-666); 4-cell bias params clear the mask
field and OR `enable` if arg else `disable` (ps:671-681), with a pull sibling
clear first (ps:673-674 via ps:542-550). Each config is an independent RMW of the
same register (ps:686).

For `gpio187_cfg_func` (pin:2477-2483; 188 = pin:2492-2498; offsets 0x02C/0x030
in the pinconf bank 0xFFF11800, udp:621-626; mux in bank 0xFFF11000 at 0x024/0x028,
pin:714-726):
- `bias-pulldown = <0 2 0 2>` → mask 0x2, arg=match(0,2,0)=0 (disable) → bit1 CLEARED.
- `bias-pullup = <0 1 0 1>` → mask 0x1, arg=match(0,1,0)=0 → bit0 CLEARED.
- `drive-strength = <0x00 0x70>` (2-cell, ps:1021-1037) → mask 0x70, arg=0 → bits[6:4] CLEARED.
- `slew-rate = <0x0 0x80>` → mask 0x80, arg=0 → bit7 CLEARED.
- **NET: cfg ← (read & ~0xF3) = (read & 0x0C) — for the observed cfg=0 (claim-0183.md:24)
  the stock kernel would write exactly 0.** The encoding cross-proof: cfg nodes
  that DO want pull-up carry `bias-pullup = <1 1 0 1>` (pin:1024, 1039, 1114,
  …) → arg=match(1,1,0)=1 → bit0 SET. So **cfg bit0 = pull-up enable**;
  gpio187/188 stock = pull-up OFF — the bus pull-ups are board-external, and our
  read-only cfg handling is already stock-equivalent. The mux word for 187/188
  func = 0x1 (pin:715/:722) with fmask 7 (udp:610) — the pmx register holds only
  the 3-bit function, so our whole-word write of 0x1 (pra:1200-1206) is also
  stock-equivalent; idle state = 0x0 (pin:718/:725) — stock unmuxes the pads
  between transactions (forkcore:861), harmless either way with external pull-ups.

### 3d. Touch driver probe (the vendor cyttsp5 stack; ran 20.257-20.56s, dmesg:3872-4117)

`cyttsp5_devtree.c:1017-1021` wires `pdata->xres/init/power/detect/irq_stat` to
the platform functions; `CYTTSP5_DETECT_HW=1` (regs:64) compiles detect in.

1. devtree parse — PRA values from dmesg:3874-3904: irq 224, rst 145,
   hid_desc_register 1, `level_irq_udelay 0` (⇒ edge IRQ, core:6722-6728:
   IRQF_TRIGGER_FALLING — the IRQ line idles HIGH), vci_power_type=1
   (LDO), vddio_power_type=1 (LDO), vci voltage NOT in dts → default **2.8 V**
   (core:6774-6777; dmesg:3907 "Not define VCI in dts, use default value 2.8V",
   dmesg:3908).
2. `cyttsp5_regulator_get` ldo17/ldo4 (core:7153 → core:6863-6885; supplies =
   `cypress_vci-supply = <&ldo17>`, `cypress_vddio-supply = <&ldo4>`, udp:449/:454).
3. **`cyttsp5_set_power(1)`** (core:7165 → core:7069-7090):
   a. `regulator_set_voltage(ldo17, 2800000)`: PMIC **reg 0x4E, mask 0x7 ← 2**
      (core:6955 → regu:183-198; table pmicdtsi:165-168 = 2.8 V at index 2).
   b. `regulator_set_voltage(ldo4, 1800000)`: **reg 0x42, mask 0x7 ← 3**
      (core:6964; table pmicdtsi:70-73 = 1.8 V at index 3).
   c. `regulator_enable(ldo17)` then `(ldo4)`: `hisi_pmic_rmw(ctrl_reg,
      0x01, 0x01)` — onoff regs **0x25 / 0x19 bit0** (core:6977/:6987 →
      regu:118-143; hisi-ctrl pmicdtsi:67/:162; the RMW is pmic:144-156, address
      = 0xFFF34000 + (reg<<2), pmic:125-156 — exactly our port's arithmetic).
   d. pinctrl normal (touch node pinctrl-0, udp:458-461).
   e. gpio_set = no-op in LDO mode (core:7001-7024; the 400 µs "1.8v→2.8v→rst"
      comment at core:7015-7016 applies to GPIO rail mode only).
4. `cpdata->init` = `cyttsp5_init` (core:7230 → plat:251-315): gpio_request 145 +
   **`gpio_direction_output(rst_gpio, 1)`** (plat:284) — the reset line is driven
   HIGH immediately after power (idle = HIGH); gpio_request 224 + input
   (plat:290-304). dmesg:3919.
5. **`cpdata->detect`** = `cyttsp5_detect` (core:7243-7246 → plat:344-367):
   `xres` (plat:235-249): **gpio145 ← 1, msleep 20 → ← 0, msleep 40 → ← 1,
   msleep 100** (plat:240-245; dmesg:4052 "cyttsp5_xres: RESET CYTTSP gpio=145"
   at 20.442 s); then msleep(100) (plat:356); then `cyttsp5_platform_detect_read`
   = `cyttsp5_adap_read_default` = **`i2c_master_recv` 1 byte at 0x1C — a pure
   read, no register write** (core:235-239, i2cbus:162-173), retry 3 (plat:352-358).
   THE FIRST I2C TRANSACTION ON THE BUS. No "Read unsuccessful" in
   dmesg.txt:4053-4109 and the probe proceeds ⇒ **it ACKed on the first try**.
6. `cyttsp5_setup_irq_gpio` (core:7263 → core:6705-6743): FALLING edge (dmesg:3894
   level_irq_udelay=0).
7. `cyttsp5_startup(cd, false)` (core:7291 — **reset=false on the first pass**):
   a. `cyttsp5_check_and_deassert_int`: pure 2-byte read ×3 (core:4867 →
      core:4809-4833) — drains any pending input report.
   b. `cyttsp5_get_hid_descriptor_` (core:4886 → core:2967-3029): WRITE 2 bytes
      (0x01 0x00) as a standalone transaction ending in STOP (i2cbus:252-288 —
      `write_read_specific` with read_buf=NULL issues only the write), then the
      response arrives via IRQ and is read as a pure read
      (`read_default_nosize`, i2cbus:175-250). **No repeated start anywhere.**
   c. mode=OPERATIONAL ⇒ `start_bootloader` output cmd → `bl_get_panel_id` →
      **`bl_launch_app`** → descriptor again (core:4899-4929). The vendor enters
      bootloader mode DELIBERATELY every boot (panel id) before launching the app.
   d. reset+retry ladder on failure: power off → 200 ms → power on → 200 ms
      (core:4877-4880), `cyttsp5_reset_and_wait` = hw xres + wait ≤ **1000 ms**
      for the reset-complete IRQ (core:4450-4479, regs:130), retry count
      CY_CORE_STARTUP_RETRY_COUNT.

Stock timeline sanity: rails on ≈20.2577 s → rst output high ≈20.2585 s → xres
20.28-20.44 s → detect read ACKed ≈20.55 s: **~290 ms rails-to-first-ACK**.

### 3e. The i2c2 + touch dts nodes — every property the stock driver consumes

- i2c2 (i2cdtsi:20-33 + udp:429-435): compatible hisilicon,designware-i2c;
  reg 0xFFD73000/0x1000; interrupts 120; clocks = `clk_gate_i2c2 &pclk`
  (names clk_i2c/apb_pclk); **clock-rate = 128000000** (udp:431); **pinctrl-0/1 =
  gpio187/188 pmx_func(0x1) + cfg_func(0) / pmx_idle(0x0) + cfg_idle(0)**
  (udp:432-434); **cs-gpios = gpio23.3, gpio23.4** (udp:435; on PRA these decode
  to 187/188, dmesg:896 — used ONLY as the recovery SCL/SDA, hisi:1012-1013);
  bus-id=2 (unused by the driver, sibling report sec 4); **delay-off=300**;
  **reset-reg-base 0xFFD7E000/0x1000**; **reset-controller-reg <0x20 0x24 0x28 5>**;
  dma properties are COMMENTED OUT (i2cdtsi:26-27) — hence "no TX DMA channel!"
  (dmesg:906).
- touch (udp:443-543): reg 0x1C; vci/vddio power types + supplies; cy,i2c_read_length
  =100; touch pinctrl (gpio055/198 — UDP rail/wake aux, LDO mode makes them
  non-load-bearing); cy,irq_gpio <&gpio28 0 0>; cy,rst_gpio <&gpio18 1 0>;
  cy,hid_desc_register=1; chip CYTT21403 (PRA, dmesg:3894) / CS445A (UDP).

## 4. THE DELTA CHECKLIST — stock op vs our port (pra_touch.c post0182/0183)

Our port's sequence (pra): ADT maps (pra:1351-1357) → COMP check (pra:1362-1370)
→ IRQ dump (pra:1376-1380) → [pratouchreset] rails RMW bit0 LDO4/LDO17 + 20 ms
(pra:1122-1168) → pad mux func 0x1 + readback (pra:1176-1222) → gpio18.1 DIR bit
+ DAT=1/10 ms/DAT=0 + readbacks (pra:1230-1270) → [0183 scan: pra_i2c_setup once
+ 0x08-0x77 one-byte reads] → BL frame (pra:1272-1293) → pra_i2c_setup lazily
(ENABLE=0 → SS 512/768 → CON=0x63 → TAR=0x1C → ENABLE=1, pra:469-497) → xfer
(pra:509-608).

| # | Stock op (anchor) | Our port | Dead-bus likelihood (reasoned) |
|---|---|---|---|
| 1 | Reset idle **HIGH** (plat:284) + reset = **LOW 40 ms** pulse, final HIGH (plat:240-245) | HIGH 10 ms then **LOW held** (pra:1247-1259); scan+BL run with line LOW | **HIGHEST** — if XRES is active-low (the vendor's own pulse direction on this hardware), we hold the IC in reset through every transaction = exactly "clean bit-0 everywhere, live controller, rails on". Explains why rails/mux/config fixes never moved the needle. |
| 2 | LDO17 vset 0x4E←2 (2.8 V), LDO4 vset 0x42←3 (1.8 V) every power-on (core:6955/:6964 → regu:196-198) | never written (pra:1152-1159 writes only onoff bit0) | **HIGH** — PMIC vset reset/boot defaults UNKNOWN from GPL; a wrong selector powers the IC out of spec → silent despite "enabled". Two RMW writes; read-print first is free. |
| 3 | IOMCU reset pulse 0xFFD7E020/24/28 bit5 at probe/resume/every timeout (hisi:139-156, :966, :1136; forkcore:772-773/:799-800) | never (only the read-only idea from i2c-research sec 6.4) | **MEDIUM** — byte-exact stock step, also the stock cure for a wedged IP; the observed clean-NACK-with-live-registers pattern is more reset-held-IC than wedged-IP, but the pulse is free and removes the variable. |
| 4 | SPKLEN 0xA0/0xA4=1, SDA_HOLD 0x7C=38, TX_TL/RX_TL=15, INTR_MASK=0, FS 112/204 + HS 48/63 (forkcore:437-462, hisi:988) | none (only SS 0x14/0x18 + CON + TAR) | **LOW as root cause** — at our 100 kHz STD mode IC_FS_SPKLEN does not gate the bus (it is the fast-mode spike filter; v1.20\* SS spike suppression is synthesis-fixed), and 100 kHz SCL-high 4-5 µs cannot be eaten by any 8-bit SPKLEN value anyway; SDA_HOLD=0 default is marginal, not a NACK generator. Still free to write for byte-exactness. |
| 5 | CON=0x65 FAST 400k (HCNT 112/LCNT 204) (hisi:915-918, 961-962) | CON=0x63 STD 100k (pra:487-488) | LOW — TT5 supports 100k (HID-over-I2C floor); but matching stock removes a variable and costs two writes. |
| 6 | pinctrl default↔idle per transfer + clk_enable/disable per transfer (forkcore:732/:739/:859/:861) | mux once, never toggled; no clk calls | NEGLIGIBLE — no gate bit exists (sibling i2c report sec 4); pads staying at func 0x1 between transfers is fine with external pull-ups. |
| 7 | Pure-read-first wire form; descriptor = write-STOP then separate reads; no restart bit (i2cbus:162-288, forkcore:604-611) | descriptor = wr + repeated-start + rd (pra:651-662); BL = one write (matches) | NEGLIGIBLE pre-ACK — a pure read and our read probe are electrically the same START+addr+R; only matters once the IC ACKs (descriptor fetch). |
| 8 | retries=3, timeout recovery ladder, SCL 0x7f-recovery | one-shot transactions (pra:509-608) | NEGLIGIBLE — robustness after the bus lives. |

Already-equal items (no delta): rails onoff bit0 + RMW form + PMIC arithmetic
(pra:1134-1159 == regu:133-135 + pmic:144-156); pad mux func 0x1 at 0x024/0x028
(pra:1200-1206 == pin:715/:722 via forkcore:739 pinctrl default); cfg word 0
(observed claim-0183.md:24 == stock net value, section 3c); COMP_TYPE check
(pra:1366-1369 == forkcore:356-369); SS 100 kHz timing (pra:480-486 — slower than
stock FAST, never faster).

## 5. Falsification tests (0184, cheapest first)

1. **Reset final level (fix #1, ~2 lines)**: after the current toggle, write
   DAT=1 (line HIGH) with readback, and re-form the pulse to the vendor shape
   (H 20 ms / **L 40 ms** / H ≥100 ms) — or minimally just append the final
   HIGH before the scan/BL. Then re-run the 0183 scan unchanged.
   - ACK appears (0x1C or anywhere) ⇒ held-reset confirmed as THE dead-bus
     cause; proceed to descriptor with the stock wire form.
   - Still 112/112 clean bit-0 ⇒ falsifies held-reset alone; keep the line HIGH
     (it is stock-correct regardless) and go to test 2.
   - Abort word changes from bit0 to bit12 (ARB_LOST) ⇒ SDA is now being held
     low — pull-up/clamp problem, not reset.
2. **VSET writes (fix #2, 2 RMWs + prints)**: read-print 0xFFF34138 (0x4E<<2)
   and 0xFFF34108 (0x42<<2) as-is, then RMW 0x4E←2, 0x42←3 (mask 0x7), readback,
   20 ms, before the onoff enables.
   - Scan ACKs after this (with test 1 also in) ⇒ under/over-voltage was real.
   - The raw print itself is evidence: if it already reads 2/3, the bootloader
     had set them and this delta was moot (falsified cheaply).
3. **IOMCU reset pulse (fix #3)**: map 0xFFD7E000, write 0x20→+0x20, poll +0x28
   bit5 ≤10 µs (print if not), write 0x20→+0x24, poll bit5 clear, THEN
   pra_i2c_setup (stock order: pulse before init, hisi:966→:984).
   - Register window dies (COMP reads 0/FF) ⇒ the IOMCU reset is our first proof
     that window liveness is reset-dependent — revert per-pulse and keep only the
     probe-time pulse.
   - Scan ACKs ⇒ wedged-IP was real; scan unchanged ⇒ variable removed.
4. **Byte-exact register init (fix #4/#5)**: inside pra_i2c_setup add
   SPKLEN(0xA0)=1, SDA_HOLD(0x7C)=38, TX_TL(0x3C)=15, RX_TL(0x38)=15, INTR_MASK
   (0x30)=0, FS 112/204, and switch CON to 0x65 with the FAST counts (keep a
   boot-arg to A/B 100k vs 400k; the TT5 tolerates both).
   - Scan ACKs only at 400k ⇒ the IC was selective about speed (rare but free to
     discover); no change ⇒ confirms these were not the blocker (expected).
5. **Vendor first-transaction replication (test only)**: before any descriptor
   attempt, issue the stock detect probe: 1-byte pure read at 0x1C, 3 tries, and
   print each result — the exact stock bring-up probe. An ACK here with a NACKing
   descriptor write would isolate the write-path (wire form) as the remaining
   difference.
6. **Anti-test**: any boot where the reset-line readback shows LOW after the new
   final HIGH write, or the PMIC vset readback != 2/3 after the RMW, invalidates
   the corresponding conclusion (the readbacks must gate the ladder, as 0180-0182
   established).

## 6. Confidence labels

- **VERIFIED** (fetched GPL source, file:line): the whole stock i2c probe register
  list and order (hisi:810-1055 + forkcore:338-467 with CONFIG_HISI_I2C_DESIGNWARE=y,
  defconfig:348-349); the IOMCU assert/poll/deassert semantics and addresses
  (hisi:139-153 + i2cdtsi:30-31); per-transfer clk/pinctrl/wait-bus/fifo-gate/
  recovery behavior (forkcore:716-872, hisi:160-185, :690-727); the exact SS/FS/HS
  HCNT/LCNT + SDA_HOLD=38 arithmetic (forkcore:253-307 formulas, script-recomputed);
  SPKLEN=1 writes (forkcore:437-439); the pinctrl 4-cell decode and the gpio187/188
  net cfg=0 + pull-up=bit0 encoding (ps:634-692/:1021-1063 + pin:2477-2505 with the
  `bias-pullup = <1 1 0 1>` cross-proof at pin:1024 etc.); the vendor power sequence
  (vset-then-enable, vci→vddio, reg 0x4E←2 / 0x42←3, bit0 on 0x25/0x19; core:7069-7090,
  regu:175-207, pmicdtsi:62-79/:157-169); the vendor xres shape h20/l40/h100 and
  idle-HIGH init (plat:235-315); the pure-read detect + write-STOP-then-read bus ops
  (plat:344-367, i2cbus:162-295, core:235-239/:4809-4833/:2967-3030); the stock PRA
  boot timeline and its silent detect success (live/dmesg.txt:892-907, 3872-3921,
  4052-4117); our port's current sequence (pra file:line throughout section 4).
- **INFERRED**: XRES active-low on this board (from the vendor pulse direction +
  mainline's logical-assert-with-DT-flag convention, ml:874-881; both agree
  physical idle HIGH / reset LOW — no datasheet anchor in-tree); the PRA product
  dts being UDP-node-equivalent (gesture/dtz/rst/irq values byte-match,
  dmesg:3894 vs udp:498/:519-522/:479-481); CONFIG_DMA_ENGINE=y in the shipped
  kernel (dmesg:906 print exists only under it, hisi:188-219); the PRA
  delay-off=300 (UDP base value; PRA SDA_HOLD could be 8 if 70 — both harmless).
- **UNKNOWN**: the hi6555 PMIC reset/boot defaults of the LDO17/LDO4 VSET
  selectors (0x4E/0x42 — not in GPL; test 2's raw print resolves it on hardware);
  whether the bootloader used the touch IC (and left rails/vsets configured) at
  our kernel entry; the exact state the bootloader leaves gpio145 in (our port
  observed cfg/pads but not the reset line's pre-toggle level beyond "dat
  readback works"); whether IC_FS_SPKLEN's reset default on this silicon is
  large (falsifiable by reading 0xA0, free in the 0181-style dump).

Key files: /home/kamion008/Ai/ios/ios-pra/work/rvr/{i2c/i2c-designware-core.c,
i2c/i2c-designware-core.h,i2c/hisi_i2c_designware.c,pinctrl/pinctrl-single.c,
cyttsp5/cyttsp5_core.c,cyttsp5/cyttsp5_i2c.c,cyttsp5/cyttsp5_platform.c,
cyttsp5/cyttsp5_devtree.c,cyttsp5/cyttsp5_regs.h,regulator/hisi_regulator.c,
mfd/hisi_pmic.c,include_mfd/hisi_pmic.h,dts/hisi_6250_i2c.dtsi,
dts/hi6250_udp_default_config.dtsi,dts/hi6250_udp_default_pin.dtsi,
dts/hisi_6555v100_pmic.dtsi,dts/merge_hi6250_defconfig,mainline/cyttsp5.c};
/home/kamion008/Ai/ios/ios-pra/work/ci183/post0182/xnu/bsd/dev/pra_touch.c;
/home/kamion008/Ai/ios/ios-pra/live/dmesg.txt; work/claim-0182.md; work/claim-0183.md;
work/i2c-research-2026-11-18.md; work/gpio18-research-2026-11-18.md.

## 7. 0184 design implication

0184 should be a bring-up-parity patch, in this order inside the existing
pratouchreset ladder: (1) re-form the gpio18.1 reset to the vendor shape and end
it HIGH — write DAT=1 (20 ms), DAT=0 (40 ms), DAT=1 with readbacks, then the 100
ms device-up wait; the "mainline asserts HIGH" comment in pra_touch.c is a
logical-gpiod translation error, the physical idle level on this board is HIGH
(plat:284/:240-245), and our current final LOW is the single best explanation for
a rails-on, mux-verified, config-verified bus that never ACKs anything; (2) write
the LDO VSET selectors before the onoff bits — 0x4E←2 (2.8 V VCI), 0x42←3
(1.8 V VDDIO), RMW mask 0x7 with raw-value print + readback, exactly the stock
set_voltage-then-enable order (core:7079-7080 → regu:196-198/:133-135); (3) pulse
the IOMCU reset once before pra_i2c_setup (write 0x20→0xFFD7E020, poll bit5 of
0xFFD7E028 ≤10 µs, write 0x20→0xFFD7E024, poll clear — hisi:139-153), keeping the
charger's no-IOMCU-write rule intact by doing it inside the gated touch path only;
(4) make pra_i2c_setup byte-exact with the stock init: FS 112/204, SPKLEN 0xA0=1
(and 0xA4=1), SDA_HOLD 0x7C=38, TX_TL/RX_TL 15/15, INTR_MASK=0, and optionally
CON=0x65 @400 kHz behind a boot-arg A/B. Keep the 0183 scan as the classifier at
the same point in the ladder: any ACK falsifies "electrically dead" and the
post-ACK work switches to the vendor wire form (write-STOP + separate pure reads,
never repeated start — i2cbus:252-288) and the vendor command ladder
(check-and-deassert 2-byte pure read → descriptor → start_bootloader → panel id →
launch_app → descriptor, core:4839-4929). Every new write keeps the 0180-0183
discipline: print-before, readback-after, one ladder rung per boot, abort-source
captured before any CLR read.

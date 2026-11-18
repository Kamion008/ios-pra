# hi6555 PMIC rails research — LDO17 (VCI) / LDO4 (VDDIO) enable regs — 2026-11-18 (read-only)

## 1. Answer

- **LDO4 (VDDIO, lowpm "LCD &TP 1.8V I/O")**: enable reg = PMIC offset 0x19 → MMIO
  **0xFFF34064**, enable bit **0** (mask 0x01); eco bit 4 (mask 0x10). Vset reg 0x42 →
  0xFFF34108, mask 0x07 (table 1.70–1.90 V).
- **LDO17 (VCI, lowpm "LCD &TP AVDD")**: enable reg = PMIC offset 0x25 → MMIO
  **0xFFF34094**, enable bit **0** (mask 0x01); eco bit 4 (mask 0x10). Vset reg 0x4E →
  0xFFF34138, mask 0x07 (table 2.60–3.30 V; stock VCI default 2.8 V, live/dmesg.txt:3907).
- Arithmetic: MMIO = 0xFFF34000 + (pmic_offset << 2). 0x19<<2=0x64, 0x25<<2=0x94 — both
  inside the 0x1000 window. ON = bit set; OFF = bit clear.

## 2. Access method (VERIFIED)

- `pmic@FFF34000`, `compatible = "hisilicon,hisi-pmic"`, reg 0xFFF34000/0x1000
  [hisi_6555v100_pmic.dtsi:24-26; live/iomem.txt:103; docs/pra-charger-contract.md:30].
  Direct MMIO — not I2C/SPI.
- **Each 8-bit PMIC register maps to a 4-byte SoC slot: addr = base + reg*4.** Driver
  comment: "The PMIC register is only 8-bit. Hisilicon SoC use hardware to map PMIC
  register into SoC mapping. At here, we are accessing SoC register with 32-bit."
  [public hi6250-8 kernel drivers/mfd/hisi_pmic.c:120-131, local copy
  /tmp/rails-research/hisi_pmic.c]; readl/writel at `regs + (reg << 2)` (:125-156);
  byte accessor `PMUSSI_REG(addr) = (addr<<2)+base` (:157-180).
- **No write-lock** on LDO paths (hisi_pmic_reg_write_lock unused for LDOs; regulator
  enable is a plain RMW, hisi_regulator.c:133-135, /tmp/rails-research/hisi_regulator.c).
- **No SoC clock gate**: hisi_pmic_probe = request_mem_region + ioremap only, no clk code
  (hisi_pmic.c:445-474); `clk_pmuctrl@0xfff34000` is `status = "disabled"` in stock
  (hisi_6250_clock.dtsi:219-222); bootloader reads the window directly
  (live/dmesg.txt:1697-1698: reg 0x1BE = 0x20 → MMIO 0xFFF346F8).

## 3. Arithmetic chain (file:line)

1. Regulator nodes: `ldo4: ldo@19` `hisilicon,hisi-ctrl = <0x19 0x01 0x10>`;
   `ldo17: ldo@25` `<0x25 0x01 0x10>` [hisi_6555v100_pmic.dtsi:62-68,157-163]. Tuple
   decode: cell0=ctrl_reg, cell1=enable_mask, cell2=eco_mode_mask [hisi_regulator.c
   :280-288].
2. Independent cross-check, same offsets+masks: lowpm `pmu_ldo4` offset 0x19 mask 0x01
   [hisi_6250_lowpm.dtsi:645,651,652, module :648]; `pmu_ldo17` offset 0x25 mask 0x01
   [:773,779,780, module :776].
3. Rail mapping: UDP touch node `cypress_vci-supply = <&ldo17>` / `cypress_vddio-supply =
   <&ldo4>`, power_type=1 (ldo) [hi6250_udp_default_config.dtsi:447-455]; stock dmesg:
   cyttsp5 `vci_power_type = 1,vddio_power_type = 1` (dmesg.txt:3908) and PMIC OCP
   registered ldo4+ldo17 (dmesg.txt:3935-3936).
4. Semantics: is_enabled = `(read(ctrl_reg) & enable_mask) != 0` [hisi_regulator.c
   :105-116]; enable = rmw(mask,mask) (:118-143); disable = rmw(mask,0) (:145-157).
   Bit set = ON — driver-defined, not guessed.

## 4. Current-state expectation

- Rails OFF ⇒ readl(0xFFF34064) bit0 = 0 and readl(0xFFF34094) bit0 = 0. Eco bit4 may be
  set independently (lowpm ECO) — never treat bit4 as rail state.
- Rail ON ⇒ bit0 = 1; LDO17 vset nibble likely 0x2 (2.8 V), LDO4 likely 0x3 (1.8 V) — INFERRED; vset UNKNOWN at handoff. Read+print vset, never write it.
- Bus-alive anchor: vbus reg 0x06 → 0xFFF34018 bit 1 = VBUS present [`hisi-pmic-vbus = <0x6 1>` hisi_6555v100_pmic.dtsi:37; semantics hisi_pmic.c:415-424].

## 5. Patch sequence (after the gpio18.1 reset window, before the I2C xfer)

1. Map 0xFFF34000/0x1000 (ml_io_map, same pattern as pra_touch.c's windows).
2. Read u32 0xFFF34018 (vbus) and print — bus-alive check (bit1 vs plug state; identical values across all regs ⇒ window dead, stop).
3. Read 0xFFF34094 (LDO17) and 0xFFF34064 (LDO4); print both hex + vset regs 0xFFF34138/0xFFF34108 low nibble. One printf line.
4. If bit0 clear: read u32, `val |= 0x01`, write u32 back (only bit0; eco bit untouched); wait >= enable-time 120 us (dts `hisi-enable-time-us`, hisi_6555v100_pmic.dtsi:75,170) before the first I2C transaction. (dts off-on-delay 20 ms applies only to re-enable after software disable — not our path.)
5. Readback both ctrl regs — bit0 must be 1; if not, print and abort the rung.

## 6. Falsification tests (cheapest first)

1. Zero-cost: pure READS (vbus + both LDO ctrl + both vset) printed in the probe. Both LDO bit0=0 with plausible vbus/vset ⇒ rails-unpowered confirmed. Either bit0=1 falsifies the unpowered-rail hypothesis for that rail.
2. Bus-alive discriminator: vbus bit1 vs actual plug state; all reads identical (0xFF/0x00) ⇒ PMUSSI window not live on our port (bus problem, not rails).
3. Decisive: if bit0=0, one RMW bit0 on both rails, readback, rerun 0178 reset+BL_LAUNCH APP. Descriptor ACK ⇒ rails were the blocker, addresses confirmed. Still NACK ⇒ rails on but IC held/failed — move to the reset/bootloader rung.

## 7. Confidence

- VERIFIED: base 0xFFF34000/0x1000 (dtsi:24-26 + live/iomem.txt:103); reg<<2 8-bit mapping
  (public hisi_pmic.c:120-180); ldo4/ldo17 offsets+enable masks (hisi_6555v100_pmic.dtsi
  :62-68,157-163 + hisi_6250_lowpm.dtsi:645-652,773-780 — two independent files); tuple
  decode + enable semantics (hisi_regulator.c:105-157,280-288); VCI/VDDIO→ldo17/ldo4 (udp
  dtsi:447-455 + dmesg.txt:3907-3908,3935-3936); no clk gate, no write-lock.
- INFERRED: handoff rail state (bootloader/lowpm inheritance UNKNOWN — the read answers
  it); vset selector guesses; public-tree driver line numbers map to the GPL dump's build
  (the dts files are identical in both trees).
- UNKNOWN: LDO4/LDO17 state at XNU entry (section 5 answers it); whether eco bit4 was
  left set by lowpm exit; PMUSSI window liveness at our entry (test 2 answers it).
- Driver source is NOT in the local hi6250-kernel tree (dts-only, no drivers/ — WORKLOG
  sec 9 statement stands for that tree); verified against public GPL dump
  hisi-oss/android_kernel_huawei_hi6250-8 (lineage-20): drivers/mfd/hisi_pmic.c,
  drivers/regulator/hisi_regulator.c, include/linux/mfd/hisi_pmic.h (copies in
  /tmp/rails-research/). ADT has no PMIC node (tools/mkadt_pra.py has no pmic refs) —
  patch should carry the addresses as literals, like pra_touch.c does.

Key files: /home/kamion008/Ai/huawei/hi6250-kernel/.../config/hi6250/{hisi_6555v100_pmic.dtsi,hisi_6250_lowpm.dtsi,hi6250_udp_default_config.dtsi,hisi_6250_clock.dtsi}; /home/kamion008/Ai/ios/ios-pra/live/{iomem.txt,dmesg.txt}; github.com/hisi-oss/android_kernel_huawei_hi6250-8 drivers/{mfd/hisi_pmic.c,regulator/hisi_regulator.c}.

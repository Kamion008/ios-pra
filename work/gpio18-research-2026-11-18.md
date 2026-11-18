# GPIO18 (gpio145) bank research — 2026-11-18 (read-only; touch reset for 0177 rung A)

## 1. Answer

- **gpio145 = bank gpio18, pin 1** (145 = 18*8 + 1; Linux gpio N = 8*bank + pin, 30 pl061 banks).
- **Bank base = 0xE8A1D000 — VERIFIED and NOT wrong; DAT = 0xE8A1D004 (pin*4), DIR = 0xE8A1D400
  (+0x400).** 0177's address was correct; it is stock-PRA-dts-derived, NOT donor-derived
  (no e8a* gpio addresses in the donor refs; 0177 took it from the 0172 header → dtsi:266-268).
- **No clock gate must be enabled**: ring42's DIR readback at 0xE8A1D400 returned bit 1 set,
  so the bank registers are live on our port. The gate still exists (see 3) as a fallback.
- The ring42 failure (`reset gpio18.1 assert readback failed dat=0`,
  research/pra-artifacts/ring42.bin) is a **pin-level signature**: pl061 DAT reads return the
  PIN STATE, and the pad is not currently driven by pl061 — most probable cause is the
  **pmx0 pinmux**, which our port never writes.

## 2. Anchor chain (gpio28 → gpio18)

- Anchor A: touch IRQ Linux gpio 224 = gpio28.0; bank gpio28 = 0xFFF1D000/0x1000
  [VERIFIED: live/dmesg.txt:3874 + udp dtsi:479; dtsi:404-406; live/iomem.txt:95-96].
- Anchor B: the stock bootloader decodes gpio N → (bank = N/8 base) + `4 << (N%8)`:
  gpio225→fff1d008, gpio93→e8a16080 (bank11 0xE8A16000), gpio51→e8a11020 (bank6
  0xE8A11000), gpio31→e8a0e200 (bank3 0xE8A0E000) [VERIFIED live/dmesg.txt:1889-1895];
  every bank base matches the dtsi table. `4 << pin` is a bootloader swapped-operand
  artifact (pin*4 = `pin << 2`), so it anchors bank BASES only, NOT the pl061 DAT stride.
  WORKLOG sec 2.2's "0xFFF1D000 + 1*4 = 0xFFF1D008 exactly" is an arithmetic slip (1*4 = 4).
- **Bank-spacing rule (VERIFIED, `hisi_6250_gpio.dtsi`) — NOT a uniform stride:**
  - gpio0..21  = 0xE8A0B000 + N*0x1000       (dtsi:13-317)
  - gpio22..27 = 0xFFF0B000 + (N-22)*0x1000  (dtsi:319-402, AO domain)
  - gpio28..30 = 0xFFF1D000 + (N-28)*0x1000  (dtsi:404-443, AO domain, after a gap)
  - Gap 0xFFF11000..0xFFF1C000 = pmx1 (0xFFF11000, iomem.txt:93) + timer@fff14000 — no gpio banks.
- Applying the rule to gpio145: 0xE8A0B000 + 18*0x1000 = 0xE8A0B000 + 0x12000 =
  **0xE8A1D000** [dtsi:266-268 `reg = <0 0xe8a1d000 0 0x1000>`; live iomem.txt:52-53
  `e8a1d000-e8a1dfff : /amba/gpio@e8a1d000`].
- **Trap:** uniform-stride arithmetic from the gpio28 anchor (0xFFF1D000 − 10*0x1000 =
  0xFFF13000) is WRONG — that address is in the pmx1/timer gap. The task's "apply the same
  rule to gpio145" premise is invalid; the two-region layout above is required.

## 3. Clock gate (CRG)

- `pclk_gpio18` = `hisilicon,hi3xxx-clkgate = <0x10 0x40000>` under `crgctrl@0xfff35000`
  (`reg = <0xfff35000 0x1000>`) → **CRG register 0xFFF35010, bit 18** (clock dtsi:1304-1309;
  crgctrl node :1096-1099). Bit==bank-number pattern VERIFIED across the family (pclk_gpio0
  = <0x10 0x1> :1160-1165; gpio21 = <0x10 0x200000> :1328-1333); parent `clk_div_cfgbus`.
  Semantics (provider base + offset, mask) INFERRED from the hi3xxx-clk-gate binding —
  driver source not on disk (tree has no drivers/).
- gpio28's AO gate for comparison: `pclk_ao_gpio6` = <0x190 0x20000> under `sctrl@0xfff0a000`
  (:794-799) → 0xFFF0A190 bit 17. AO clocks default on — why gpio28 read fine with no gate code.
- **Must it be enabled? NO (on-device evidence):** 0177 read DIR, wrote dir|0x2, read back
  and PASSED the dir check (no "dir readback failed" in ring42) — a read of 0xE8A1D400
  returned bit 1 set; a pclk-gated pl061 reads 0 in DIR too. UNKNOWN whether the bootloader
  leaves it on or it is reset-default-on.

## 4. Toggle sequence (0177 layout, unchanged) and expected readback

1. DIR 0xE8A1D400: read-modify-write bit 1 (0x2); readback must show bit 1 (0177 passes).
2. DAT 0xE8A1D004: write 0x1 (assert HIGH per mainline cyttsp5.c:873-874); readback bit 0
   set — only true once the pad is actually muxed to pl061 and driven.
3. Pulse >= 10 us (0177: 10 ms), deassert write 0x0, readback bit 0 clear; 20 ms device-up
   delay; then BL_LAUNCH_APP (11-byte frame, as landed in 0177).
4. Current failure: step 2 read 0 with step 1 passing ⇒ pin state ≠ driven level.

## 5. Missing prerequisite: pmx0 pinmux (root-cause hypothesis, INFERRED)

- gpio18's pad range: `gpio-ranges = <&pmx0 0 51 2>` (dtsi:272) ⇒ gpio18.0 = pmx0 pin 51,
  **gpio18.1 = pmx0 pin 52**; pmx0 = `pinmux@e896c000` (pinctrl dtsi:4; live iomem.txt:11).
- pinctrl-single pin N sits at offset N*4 ⇒ pad register = 0xE896C000 + 52*4 = 0xD0 →
  **0xE896C0D0**; UDP-default function value **0x0 = GPIO** (hi6250_udp_default_pin.dtsi
  :362-365 `gpio055_pmx_func <0x0D0 0x0>`; also :1659-1666 `gpio052_cfg_func <0x0D0 0>`
  with bias/drive cells). INFERRED for the PRA board itself — no prague pin dtsi in the
  tree; UDP default is the team's existing touch reference (WORKLOG cites it throughout).
- The stock kernel wrote this mux when cyttsp5 claimed gpio145; our port never touches pmx0,
  so the pad stays in whatever function the bootloader left (UNKNOWN at our kernel entry).
- Alternative (weaker) cause: pad clamped externally (touch IC unpowered — VCI=LDO17 /
  VDDIO=LDO4 via PMIC MMIO 0xFFF34000, WORKLOG sec 9) — a pl061 drive would win over a
  passive clamp, so pinmux stays primary.

## 6. Falsification tests (cheapest first)

1. Zero-cost: print the already-captured idle `dir=` in the dat-failure printf (0177 reads
   `dir` first but never prints it on that path). Expect dir != 0 (bit 1 set); a dir=0
   print falsifies the live-bank claim.
2. Decisive: one pmx0 write 0xE896C0D0 = 0 before the toggle, then re-run. DAT readback 1
   afterwards ⇒ address/layout confirmed, pinmux was the blocker. DAT still 0 ⇒ pad is
   externally clamped ⇒ move to the touch-rail rung, not a new bank address.
3. Anti-test: any "dir readback failed dir=0" at 0xE8A1D400 falsifies this whole
   bank-base + clock analysis.

## 7. Confidence labels

- VERIFIED: gpio18 base (dtsi:266-268 + iomem.txt:52-53 + ring42 DIR readback); gpio28
  anchor (dtsi:404-406 + iomem.txt:95-96 + dmesg.txt:3874/1893-1895); bank-spacing table;
  CRG 0xFFF35010 bit 18 / SCTRL 0xFFF0A190 bit 17 defs (clock dtsi file:line); pmx0 base
  0xE896C000; UDP mux value 0 at offset 0x0D0; ring42 failure text.
- INFERRED: DAT/DIR offsets (pin*4 / 0x400, ARM PL061 TRM DDI0224 — no pl061 driver source
  on disk; consistent with 0172's zero reads at gpio28.0 = +0x0); hi3xxx-clkgate semantics;
  pinmux as root cause; PRA pad mux value 0.
- UNKNOWN: PRA-specific pmx0 0x0D0 function/bias values; touch rail state at our entry;
  why the pclk gate is on (default vs bootloader); bootloader's 4<<pin offset (bug vs intent).

Key files: /home/kamion008/Ai/huawei/hi6250-kernel/arch/arm64/boot/dts/auto-generate/{overlay,config}/hi6250/
(hisi_6250_gpio.dtsi, hisi_6250_clock.dtsi, hisi_6250_pinctrl.dtsi, hi6250_udp_default_pin.dtsi);
/home/kamion008/Ai/ios/ios-pra/live/{dmesg.txt,iomem.txt}; .../research/pra-artifacts/ring42.bin;
.../xnu/patches/0177-pra-touch-hid.patch; .../research/driver-specs/touch-work/WORKLOG.md (sec 2.2).

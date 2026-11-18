# DW_apb_i2c (0xFFD73000 "i2c2") register + abort-source research — 2026-11-18 (read-only)

## 1. Answer

- **Register map is the STANDARD DW_apb_i2c map; TX_ABRT_SOURCE = 0x80 confirmed.**
  Linux v6.1 `drivers/i2c/busses/i2c-designware-core.h:46-84` defines every offset we
  need: CON 0x00, TAR 0x04, SAR 0x08, DATA_CMD 0x10, SS_SCL_HCNT/LCNT 0x14/0x18,
  FS_SCL_HCNT/LCNT 0x1C/0x20, HS 0x24/0x28, INTR_STAT 0x2C, INTR_MASK 0x30,
  RAW_INTR_STAT 0x34, CLR_TX_ABRT 0x54, CLR_STOP_DET 0x60, ENABLE 0x6C, STATUS 0x70,
  TXFLR 0x74, RXFLR 0x78, **TX_ABRT_SOURCE 0x80**, ENABLE_STATUS 0x9C, COMP_PARAM_1
  0xF4, COMP_VERSION 0xF8, COMP_TYPE 0xFC (VERIFIED). The Huawei fork uses the same
  offsets and adds nothing inside the window except using the standard DMA regs
  0x88/0x8C/0x90 and IC_FS_SPKLEN **0xA0** (fork core.c:70-73; also 0xA0 in the
  RP2040 DW register dump :2566).
- **COMP_TYPE=0x44570140 is the genuine DW_apb_i2c component ID** — Linux
  `DW_IC_COMP_TYPE_VALUE 0x44570140` (v6.1 core.h:84); the latest master header
  annotates it `/* "DW" + 0x0140 */` (i2c-designware-core.h:44). Our probe reads
  exactly that (PRA-LX1-noted.md:1609-1610) ⇒ the standard map applies at 0xFFD73000.
- **COMP_VERSION=0x3132302a decodes to DW_apb_i2c v1.20\* ("120\*"), NOT "2.20a" and
  NOT "120a".** The encoding is 4 ASCII chars MSB→LSB with `*` = revision wildcard:
  0x31 '1', 0x32 '2', 0x30 '0', 0x2A '*'. Anchor: latest Linux master header
  `#define DW_IC_SDA_HOLD_MIN_VERS 0x3131312A /* "111*" == v1.11* */`
  (i2c-designware-core.h:43). So v1.11* (0x3131312A) ≤ our v1.20* (0x3132302A):
  the IC_SDA_HOLD register (0x7C) exists (v6.1 common.c:399-403 uses this exact
  numeric compare), and v1.20-era features (STOP bit 9, TX_ABRT_SOURCE, USER_ABRT)
  are in-era for this silicon.
- **TX_ABRT_SOURCE bit table (full decode in section 3.2).** For the diagnostic
  print: bit 0 = 7-bit address NACK, bit 3 = data NACK, bit 12 = arb lost, bit 9 =
  SBYTE_NORSTRT (STICKY), bits 8/10 = the other restart-disabled aborts (HS / 10-bit
  read), bit 16 = USER_ABRT, bits [31:23] = TX_FLUSH_CNT = how many queued TX
  commands the abort flushed (locates the failure byte). **Corrections to the task
  premises: SBYTE_NORSTRT is bit 9 (not 8); ARB_LOST is bit 12 (not 11); bit 11 is
  MASTER_DIS; bit 8 is ABRT_HS_NORSTRT; TX_FLUSH_CNT is [31:23] (not [23:16]).**
- **The Huawei "i2c_designware-hs" fork (drivers/i2c/busses/hisi_i2c_designware.c,
  hisi-oss/android_kernel_huawei_hi6250-8 lineage-20) does NOT change the register
  map.** Its additions: a separate IOMCU reset window 0xFFD7E000 (assert w 0x20→
  0xFFD7E020, status r 0xFFD7E028, deassert w 0xFFD7E024, all BIT(5)=i2c2), a pinmux
  idle hook, per-transfer clk_enable/clk_disable, DMA, and a fork-only SPKLEN write.
  Driver name string "i2c_designware-hs" (hisi_i2c_designware.c:1154) matches
  live/dmesg.txt:892-907 line for line.
- **0xFFD73000 is ABSENT from live/iomem.txt** (only ffd70000 spi, ffd74000 uart,
  ffd77000 dma appear, :75-79). INFERRED explanation: the hisi driver uses plain
  `ioremap` without `request_mem_region` (hisi_i2c_designware.c:853), so the region
  never appears in /proc/iomem — absence is expected, not evidence of a dead window.
- **No clock-gate write is required for i2c2**: `clk_gate_i2c2` is a
  `fixed-factor-clock` off the fixed 128 MHz `clk_fll_src` (hisi_6250_clock.dtsi
  :3024-3031, :22-27) — no hardware gate bit (contrast clk_gate_i2c4 =
  `hisilicon,hi3xxx-clk-gate` <0x20 0x8000000> = PERI_CRG 0xFFF35020 bit 27 for the
  other host, :2107-2114). Empirically the controller answers (COMP_VERSION read),
  so it is neither reset-held nor clock-dead at our entry — the task's "clock dead"
  hypothesis is already falsified (PRA-LX1-noted.md:1609-1611: a clock-gated hi6250
  DW host returns a synchronous external abort, not data).
- **0181 print order (CRITICAL): read TX_ABRT_SOURCE (0x80) BEFORE reading
  CLR_TX_ABRT (0x54)** — upstream reads+preserves ABRT_SOURCE first, then does the
  read-to-clear, with the comment "The IC_TX_ABRT_SOURCE register is cleared whenever
  the IC_CLR_TX_ABRT is read. Preserve it beforehand." (i2c-designware-master.c
  :687-694; identical code+comment in the fork core.c:1005-1011). The existing
  pra_touch.c error paths destroy the evidence at pra_touch.c:520 before printing
  anything.

## 2. Access method / anchor chain

- Web (VERIFIED sources, fetched to /tmp/i2c-research/):
  - Linux v6.1 tag: `i2c-designware-core.h`, `i2c-designware-master.c`,
    `i2c-designware-common.c` (the shared code file is named common.c in v6.1; the
    older name i2c-designware-core.c 404s on that tag), plus the `master`-branch
    header for the version-decode comment. URLs:
    raw.githubusercontent.com/torvalds/linux/v6.1/drivers/i2c/busses/{i2c-designware-core.h,i2c-designware-master.c,i2c-designware-common.c}
    and .../master/drivers/i2c/busses/i2c-designware-core.h.
  - Huawei GPL dump: raw.githubusercontent.com/hisi-oss/android_kernel_huawei_hi6250-8/lineage-20/drivers/i2c/busses/{hisi_i2c_designware.c,i2c-designware-core.c,i2c-designware-core.h,i2c-designware-platdrv.c}.
  - RP2040 pico-sdk register header (raspberry-pi's licensed DW_apb_i2c RTL,
    per-register databook text): raw.githubusercontent.com/raspberrypi/pico-sdk/master/src/rp2040/hardware_regs/include/hardware/regs/i2c.h — used as the public databook proxy for field-level semantics Linux never quotes (TAR write rule, bit-9 stickiness, TX_FLUSH_CNT, ABORT-bit flush).
- Local (all file:line in section 3-6): /home/kamion008/Ai/ios/ios-pra/work/ci181/post0180/xnu/bsd/dev/pra_touch.c
  (the live driver — NOTE: the task's path work/post0180/... does not exist; the
  post0180 tree lives under work/ci181/), xnu/patches/0152-pra-charger.patch,
  xnu/patches/0172-pra-touch-probe.patch, live/{dmesg.txt,iomem.txt},
  /home/kamion008/Ai/huawei/hi6250-kernel/arch/arm64/boot/dts/auto-generate/{config,overlay}/hi6250/
  {hisi_6250_i2c.dtsi,hisi_6250_clock.dtsi,hi6250_udp_default_config.dtsi,hi6250_udp_default_pin.dtsi,hi6250_emulator_config.dts}.
- Config/ and overlay/ dtsi copies carry identical line numbers for everything cited
  (checked both for the i2c and clock files).

## 3. Semantics chain

### 3.1 Register map (Linux v6.1 i2c-designware-core.h, torvalds/linux tag v6.1)

| Offset | Name | core.h line | Notes |
|---|---|---|---|
| 0x00 | IC_CON | :46 | write only when disabled (:3.3c) |
| 0x04 | IC_TAR | :47 | write only when IC_ENABLE[0]=0; bit 12 = 10-bit |
| 0x08 | IC_SAR | :48 | slave addr (unused by us) |
| 0x10 | IC_DATA_CMD | :49 | bit 8 CMD=READ, bit 9 STOP, bit 10 RESTART |
| 0x14 | IC_SS_SCL_HCNT | :50 | written by pra_i2c_setup |
| 0x18 | IC_SS_SCL_LCNT | :51 | written by pra_i2c_setup |
| 0x1C | IC_FS_SCL_HCNT | :52 | |
| 0x20 | IC_FS_SCL_LCNT | :53 | |
| 0x24 | IC_HS_SCL_HCNT | :54 | |
| 0x28 | IC_HS_SCL_LCNT | :55 | |
| 0x2C | IC_INTR_STAT | :56 | = RAW & MASK (master.c:658-670) |
| 0x30 | IC_INTR_MASK | :57 | |
| 0x34 | IC_RAW_INTR_STAT | :58 | TX_ABRT = bit 6 (:92) |
| 0x38/0x3C | IC_RX_TL/IC_TX_TL | :59-60 | reset 0 |
| 0x40 | IC_CLR_INTR | :61 | |
| 0x44-0x50 | CLR_RX_UNDER/OVER/TX_OVER/RD_REQ | :62-65 | |
| 0x54 | IC_CLR_TX_ABRT | :66 | read-to-clear; clears ABRT_SOURCE (except bit 9) |
| 0x58-0x68 | CLR_RX_DONE/ACTIVITY/STOP_DET/START_DET/GEN_CALL | :67-71 | |
| 0x6C | IC_ENABLE | :72 | bit 0 EN, bit 1 ABORT, bit 2 TX_CMD_BLOCK (v2.x) |
| 0x70 | IC_STATUS | :73 | see 3.3e |
| 0x74 | IC_TXFLR | :74 | our push gate |
| 0x78 | IC_RXFLR | :75 | flushed on abort (RP2040 :1834-1837) |
| 0x7C | IC_SDA_HOLD | :76 | exists: version ≥ 1.11* (common.c:399-403) |
| **0x80** | **IC_TX_ABRT_SOURCE** | **:77** | **see 3.2** |
| 0x9C | IC_ENABLE_STATUS | :78 | bit 0 IC_EN |
| 0xA8 | IC_CLR_RESTART_DET | :79 | |
| 0xF4 | IC_COMP_PARAM_1 | :80 | TX depth [23:16], RX depth [15:8] |
| 0xF8 | IC_COMP_VERSION | :81 | 0x3132302a = "120*" = v1.20* |
| 0xFC | IC_COMP_TYPE | :83 | 0x44570140 expected (:84) |

IC_FS_SPKLEN = 0xA0 / IC_HS_SPKLEN = 0xA4: not in the v6.1 Linux header (Linux
never touches them); VERIFIED for this silicon via the fork defines + init write of 1
(fork core.c:72-73, :437-439) and RP2040 (:2557-2568). Our port never writes them
(reset default from the IC_DEFAULT_FS_SPKLEN synthesis param applies; RP2040 default
0x7 = fine at 100 kHz; our actual default UNKNOWN — 0181 can read it for free).

### 3.2 IC_TX_ABRT_SOURCE (0x80) — full bit decode

Bit numbers: Linux v6.1 core.h:145-158 (0-15) + defines :160-173; strings
i2c-designware-common.c:31-60. Fork extensions (SAME silicon): ABRT_HS_ACKDET=6,
ABRT_HS_NORSTRT=8, ABRT_USER_ABRT=16 with strings (fork core.c:134-146, :167-196).
RP2040 register text: bit 16 (:1938-1953), TX_FLUSH_CNT [31:23] (:1924-1936), bit-9
stickiness (:1908-1918, :2074-2095).

| Bit | Name | Meaning (abbreviated from the string tables) |
|---|---|---|
| 0 | ABRT_7B_ADDR_NOACK | "slave address not acknowledged (7bit mode)" — the target-address NACK |
| 1 | ABRT_10ADDR1_NOACK | first address byte NACK (10-bit) |
| 2 | ABRT_10ADDR2_NOACK | second address byte NACK (10-bit) |
| 3 | ABRT_TXDATA_NOACK | "data not acknowledged" — IC ACKed its address but NACKed payload |
| 4 | ABRT_GCALL_NOACK | no ACK for general call |
| 5 | ABRT_GCALL_READ | read after general call |
| 6 | ABRT_HS_ACKDET | HS master code ACKed (fork string; not defined by Linux) |
| 7 | ABRT_SBYTE_ACKDET | start byte ACKed |
| 8 | ABRT_HS_NORSTRT | restart disabled + HS-mode data transfer attempted (fork string) |
| 9 | ABRT_SBYTE_NORSTRT | START byte attempted with restart disabled — **STICKY**: cleared only after the source is fixed (RESTART_EN=1 and IC_TAR[11]/[10] cleared); "bit 9 clears for one cycle and then gets reasserted" (RP2040 :2074-2095) |
| 10 | ABRT_10B_RD_NORSTRT | 10-bit read with restart disabled |
| 11 | ABRT_MASTER_DIS | "trying to use disabled adapter" |
| 12 | ARB_LOST | "lost arbitration" |
| 13 | ABRT_SLAVE_FLUSH_TXFIFO | slave-mode: flush TX FIFO on read command |
| 14 | ABRT_SLAVE_ARBLOST | slave lost bus while transmitting |
| 15 | ABRT_SLAVE_RD_INTX | slave-transmitter misconfiguration |
| 16 | ABRT_USER_ABRT | software set IC_ENABLE[1] (ABORT); fork: "master has detected the transfer abort(IC_ENABLE(1))" |
| 17 | ABRT_SDA_STUCK_AT_LOW | newer-DW abort, SDA stuck low while generating START — databook-sourced ([Scribd DW-apb-i2c databook copy](https://www.scribd.com/document/813110146/DW-apb-i2c-databook)); fork does NOT define it for this silicon ⇒ likely absent on v1.20* — UNKNOWN |
| [31:23] | TX_FLUSH_CNT | "number of Tx FIFO Data Commands which are flushed due to TX_ABRT interrupt. It is cleared whenever I2C is disabled" (RP2040 :1924-1936) — a count, not a cause |

Clearing semantics: "Except for Bit 9, this register is cleared whenever the
IC_CLR_TX_ABRT register or the IC_CLR_INTR register is read" (RP2040 :1908-1910);
TX_FLUSH_CNT additionally clears on disable (:1929-1931); a Synopsys databook preface
also notes clearing on IC_ENABLE[0] 1→0 ([iopress databook preface PDF](https://www.iopress.info/Downloads/designware-dwapbi2c-databook-preface-preface.pdf)) — our setup's disable
(pra_touch.c:403) clears stale evidence anyway, so the pre-transaction CLR_TX_ABRT
read at pra_touch.c:448 guarantees the printed source belongs to THIS transaction.

Suggested printf decode order (most-diagnostic-first for a master-mode 7-bit write):
**bit 0** (target NACK — the expected dead-IC signature), **bit 3** (data NACK — IC
alive, rejects payload), **bit 12** (arb lost — bus stuck low), **bit 11** (master
disabled — config lost), **bit 9, 10, 8** (restart family — config corruption,
impossible in our flow), **bit 16** (software abort), bits 4/5/7/6 (general-call /
start-byte / HS — impossible), bits 13/14/15 (slave-mode noise), then TX_FLUSH_CNT
count (13 = 0x0D expected for the 13-byte BL frame aborted at address; lower count =
bytes already sent ⇒ locates the failing byte). One line:
`abrt=%08x b0=%d b3=%d b12=%d b11=%d b9=%d b10=%d b8=%d b16=%d flush=%u`.

### 3.3 Critical quirks for a hand-rolled master (Linux master.c/common.c as reference)

**a. IC_TAR (0x04) write rule.** "This register can be written to only when
IC_ENABLE[0] is set to 0" (RP2040 IC_TAR block :293-295). Dynamic TAR update is a
synthesis parameter that "can't be detected from registers" (master.c:222-228), so
the reference driver always disables first: __i2c_dw_disable → TAR write → enable
(master.c:210-253 at :217/:238-239/:245; fork core.c:489-533 at :495/:518/:524).
Writing TAR while enabled is ignored (no effect) unless that parameter was
synthesized on — i.e. a TAR write that silently does not take. **Our code is
compliant**: pra_i2c_setup disables first and writes TAR before re-enabling
(pra_touch.c:403-420), same as pra_charger.c's pattern it mirrors. If the 0181 TAR
readback shows != 0x1C, the config never took (write-while-enabled or IOMCU reset
between steps).

**b. Post-abort unblocking.** On any TX_ABRT the hardware flushes the TX/RX FIFOs:
"Anytime TX_ABRT is set, the contents of the tx/rx buffers are flushed. Make sure to
skip them" (master.c:737-740; fork core.c:1056-1059; RXFLR comment RP2040
:1834-1837). The abort stays latched in TX_ABRT_SOURCE + RAW_INTR_STAT bit 6 until
software reads IC_CLR_TX_ABRT (RP2040 :1908-1910) — the FIFO is flushed, not frozen,
but TXFLR reads 0 after an abort and TX_FLUSH_CNT tells you what was lost. The fork
additionally hard-resets the whole controller via the IOMCU reset register whenever
TXFLR/RXFLR are non-zero at xfer start or the completion times out (fork core.c
:768-776, :788-804) — the stock kernel's own recovery for a wedged DW. Software must
not start a new transaction with a pending un-cleared abort; our driver's
CLR_TX_ABRT read before pushing (pra_touch.c:448) satisfies this.

**c. IC_CON minimal correct value.** SPEED field is bits **[2:1]** (not [1:0]):
1 = 100 kHz std, 2 = fast, 3 = HS (RP2040 SPEED field :255-268, MSB 2/LSB 1; Linux
v6.1 :29-32 with `SPEED_MASK GENMASK(2,1)`). Minimal master config =
MASTER(bit0) | 1<<1 (std) | RESTART_EN(bit5) | SLAVE_DISABLE(bit6) = **0x63** —
exactly what pra_touch.c writes (pra_touch.c:171-174, :416-417). The stock fork ran
FAST by default (0x4 ⇒ CON 0x65; hisi_i2c_designware.c:915-925 default
`speed_mode = DW_IC_CON_SPEED_FAST` with "no speed-mode property, use default!",
dmesg.txt:898; master_cfg at :961-962) — both fine for the TT5. RESTART_EN=0 does
NOT abort a wr->rd: "if IC_RESTART_EN is 0, a STOP followed by a START is issued"
instead of the repeated start (RP2040 DATA_CMD RESTART field :432-447). CON itself is
write-only-when-disabled: "This register can be written only when the DW_apb_i2c is
disabled, which corresponds to the IC_ENABLE[0] register being set to 0. Writes at
other times have no effect" (RP2040 :93-96) — another silent-ignore trap if anyone
reconfigures without disabling first (our code always disables).

**d. IC_DATA_CMD byte semantics + version decode.** bit 8 = CMD (1 = read), bit 9 =
STOP ("STOP is issued after this byte, regardless of whether or not the Tx FIFO is
empty" — RP2040 :470-500), bit 10 = RESTART, bit 11 = FIRST_DATA_BYTE (read-only,
v2.x). Upstream uses BIT(9)/BIT(10) (master.c:428-435, :443-444); the fork builds
`cmd | 0x100` with BIT(9) on the last byte in its DMA path — code that runs on THIS
silicon in the stock kernel (fork core.c:599-623) ⇒ STOP-bit-9 exists on v1.20*
(VERIFIED-by-fork). COMP_VERSION decode: 0x3132302a = ASCII "120*" = **v1.20\*** (see
section 1; the task's "120a" misreads 0x2A as 'a' — 0x61; "2.20a" would need a
leading 0x32). In that version TX_ABRT_SOURCE (0x80) and the abort framework exist
(fork reads/uses them on this silicon), IC_SDA_HOLD exists (≥1.11*), SPKLEN
plausibly exists (fork writes 0xA0; exact intro version UNKNOWN).

**e. IC_STATUS (0x70) bits** (Linux v6.1 core.h:110-113; RP2040 :1684-1745):
ACTIVITY bit 0, TFNF bit 1, TFE bit 2, RFNE bit 3, RX_FULL bit 4, MST_ACTIVITY
bit 5, SLV_ACTIVITY bit 6; when disabled, bits 1 and 2 read 1 and the reset value is
0x06. Upstream's busy-wait polls STATUS & ACTIVITY only (common.c:530-532); our
DW_IC_STATUS_BUSY 0x21 = ACTIVITY|MST_ACTIVITY (pra_touch.c:180, :383-391) is a
stricter master-FSM idle check — fine. Polling TXFLR (0x74) directly, as
pra_i2c_xfer does (pra_touch.c:459), is the robust gate; TFE (bit 2) is the
"FIFO completely empty" alternative.

**f. IC_ENABLE_STATUS (0x9C).** bit 0 IC_EN follows ENABLE a few clocks later
(v6.1 common.c:439-463 polls it with 25-250 us sleeps, 100 tries, "as described in
the DesignWare I2C databook" :454-458; RP2040 :2458-2545). Our pra_i2c_wait_enable
polls it bounded (pra_touch.c:368-378). The Linux dummy read after enable
("avoid the register getting stuck on Bay Trail", master.c:247-248) is a
platform-specific workaround we can ignore. If 0181 sees ENABLE_STATUS.IC_EN == 0
while ENABLE == 1, the enable never took (reset/clock domain problem).

## 4. The Huawei fork ("i2c_designware-hs")

- **Identity**: drivers/i2c/busses/hisi_i2c_designware.c, platform driver name
  `"i2c_designware-hs"` (:1154), compatible `"hisilicon,designware-i2c"` (:1082).
  Every probe message in live/dmesg.txt:894-907 matches a print in this file:
  phy_addr (:865), vir_addr (:868), cs-gpios (:883), clock rate (:907),
  speed-mode/retries/timeout defaults (:917/:929/:937), tx/rx_fifo_depth (:973),
  input_clock_khz (:85 via :977 and again from i2c_dw_init), retries/timeout (:1028),
  "no TX DMA channel!" (:219), "i2c probe succeed!" (:1047). The stock dmesg's
  `i2c_bus_numb` lines (:892-893) are NOT in the lineage-20 dump (INFERRED: the EMUI
  build adds that property; it defaults bus 0, which is why the touch IC lives on
  `i2c-0/0-001c` under ffd73000.i2c — dmesg.txt:4827 — despite `bus-id = <2>` in the
  base dtsi, hisi_6250_i2c.dtsi:28, which this driver never parses).
- **Register map: UNCHANGED.** Fork core.c:40-80 is the standard map (same offsets
  as Linux v6.1) plus standard DMA regs (DMA_CR 0x88, TDLR 0x8C, RDLR 0x90) and
  SPKLEN 0xA0/0xA4 (HISI-guarded, :71-74). hisi_i2c_designware.c redefines only
  CON/TAR/ENABLE/STATUS/TXFLR/RXFLR/TX_ABRT_SOURCE/DATA_CMD (:39-57) with the same
  values. Nothing custom inside the 0x1000 window. Register access is 32-bit
  (`ACCESS_32BIT`, hisi:964; dw_readl/dw_writel fork core.c:225-251) — matches our
  32-bit MMIO port; i2c_dw_init verifies COMP_TYPE==0x44570140 with a
  swap/16-bit fallback (fork core.c:356-369), and the stock probe passed ⇒ our
  plain-32-bit reads of the map are the right form.
- **Reset register at 0xFFD7E000 (IOMCU_CONFIG/IOMCU CRG).** dts tuple
  `reset-controller-reg = <0x20 0x24 0x28 5>` (hisi_6250_i2c.dtsi:31; i2c0 uses bit 3,
  :16) is parsed into priv{reset_enable_off=0x20, reset_disable_off=0x24,
  reset_status_off=0x28, reset_bit=5} (hisi:875-879, :890-893; struct fork core.h
  :45-52). hs_i2c_dw_reset_controller (hisi:126-156): **assert = writel(BIT(5)=0x20,
  0xFFD7E020)**, poll 0xFFD7E028 bit5 until set (≤10 us); **deassert =
  writel(0x20, 0xFFD7E024)**, poll bit5 until clear. Called at probe BEFORE
  i2c_dw_init (hisi:966), at resume (hisi:1136), and after every xfer/DMA timeout or
  non-zero-FIFO start (fork core.c:772-773, :799-800, :820). So the stock kernel
  always pulses this reset line at probe. **Could i2c2 be held in reset at our XNU
  entry? NO** — COMP_VERSION/COMP_TYPE read fine (pra_touch.c:1151-1154;
  PRA-LX1-noted.md:1609-1610), and the established hi6250 behavior is that a
  clock-gated/gated-out DW host external-aborts on read (SES) rather than returning
  data (PRA-LX1-noted.md:1611, host 1 = 0xFDF0D000). 0xFFD7E000 is the IOMCU clock/
  reset controller (dtsi comment :15/:30 "IOMCU_CONFIG";
  hi6250_emulator_config.dts:122-126 `hisi_iomcuctrl: crgctrl@0xFFD7e000`).
  pra_charger.c already maps this window read-only and prints reset_value =
  readl(0xFFD7E000+0) (0152-pra-charger.patch:145,155,364-375) — 0181 can extend
  that pattern to +0x20/+0x24/+0x28 raw reads (VERIFIED semantics above; writes stay
  forbidden per the charger's own rule, :338-340).
- **Clocks**: dts `clocks = <&clk_gate_i2c2 &pclk>` (hisi_6250_i2c.dtsi:24);
  `clk_gate_i2c2` = fixed-factor-clock, parent `clk_fll_src` = fixed 128 MHz,
  div 1/mult 1 (hisi_6250_clock.dtsi:3024-3031, :22-27) — **no gate bit** (contrast
  clk_gate_i2c4 = hi3xxx-clk-gate <0x20 0x8000000>, :2107-2114). The fork's per-xfer
  clk_enable/clk_disable (fork core.c:732, :859; probe prepare :943, disable :1045)
  therefore toggles no hardware gate on this bus — no clock-gate requirement for our
  port. The stock dmesg prints BOTH "clock rate is 19200000" (dmesg.txt:897 = the dt
  `clock-rate` property value, hisi:903-907; PRA product dts sets 19.2 MHz vs the UDP
  config's 128000000, hi6250_udp_default_config.dtsi:431) and
  "input_clock_khz value is 128000" (:902-903 = clk_get_rate, hisi:80-88) — the
  functional clock IS 128 MHz, matching pra_touch.c's timing choice (pra_touch.c
  :29-38, :189).
- **FIFO depths 64/64** read from COMP_PARAM_1 ((p>>16 & 0xff)+1 / (p>>8 & 0xff)+1,
  hisi:969-975; dmesg.txt:901) ⇒ COMP_PARAM_1 ≈ 0x3F3F____ on our silicon; same
  formula upstream (common.c:582-588). The fork programs TX_TL/RX_TL = 15/15 and DMA
  thresholds (fork core.c:452-456); we leave them at reset 0, which only matters for
  TX_EMPTY/RX_FULL interrupts we don't use.

## 5. Local driver state (post0180 pra_touch.c) and current-state expectation

- **Defines present** (pra_touch.c:156-182): CON 0x00, TAR 0x04, DATA_CMD 0x10,
  SS_SCL_HCNT/LCNT 0x14/0x18, RAW_INTR_STAT 0x34, CLR_TX_ABRT 0x54 (read-to-clear),
  CLR_STOP_DET 0x60, ENABLE 0x6C, STATUS 0x70, TXFLR 0x74, ENABLE_STATUS 0x9C,
  COMP_VERSION 0xF8, COMP_TYPE 0xFC; CON bits MASTER/SPEED_STD 0x02/RESTART_EN
  0x20/SLAVE_DIS 0x40, CMD_READ 0x100, CMD_STOP 0x200, INTR RX_FULL/TX_ABRT/STOP_DET,
  STATUS_BUSY 0x21, RFNE 0x08, EN_STATUS_IC_EN, TXFLR_PUSH 60.
- **MISSING: DW_IC_TX_ABRT_SOURCE 0x80** — confirmed absent by grep. That is THE gap
  for 0181: the driver classifies any TX_ABRT as ENXIO ("address NACK",
  pra_touch.c:456/:484/:506 → print at :1185-1188) without ever reading the abort
  source, so the "err=6 = address NACK" label is the driver's own assumption, not a
  hardware-verified fact. Also missing (all cheap read-only adds): SAR 0x08,
  FS_SCL_HCNT/LCNT 0x1C/0x20, INTR_MASK 0x30, RXFLR 0x78, SDA_HOLD 0x7C,
  COMP_PARAM_1 0xF4, FS_SPKLEN 0xA0.
- **Failure path order today**: TX_ABRT detected in the push/drain/stop loops sets
  error=ENXIO (:456/:484/:506), falls to :520-521 which reads CLR_TX_ABRT +
  CLR_STOP_DET (destroying the abort source), then :522-526 clears pra_tar to force
  re-setup. pra_touch_reset_launch (:949-1091) enables the rails (0180 block
  :968-1014, verified live: vbus=0x2, both LDO bit0 set per claim-0180), toggles
  gpio18.1 readback-verified (:1015-1060), builds + sends the 13-byte BL frame
  (2 reg bytes + 11 payload, :1062-1075 via pra_touch_output_write :619-630 →
  pra_touch_txn → pra_i2c_xfer), and the BL write is what returns err=6 (claim-0180).
- **Current-state expectation for the next boot**: rails ON (0180 verified), reset
  line toggled, COMP_VERSION/COMP_TYPE read fine again, BL_LAUNCH_APP again err=6
  unless 0181 changes something — 0181 must NOT change the transaction, only wrap
  the failure exit with the register dump (section 6), so the boot stays
  byte-for-byte comparable.

## 6. Patch sequence implications (0181)

1. Add `#define DW_IC_TX_ABRT_SOURCE 0x80u` (plus optional read-only COMP_PARAM_1
   0xF4 / RXFLR 0x78 / FS_SPKLEN 0xA0) to the define block at pra_touch.c:156-169.
2. In pra_i2c_xfer, on EVERY error exit (ENXIO and ETIMEDOUT paths, :474-476,
   :496-498, :501-518) and BEFORE the CLR_TX_ABRT read at :520: read RAW_INTR_STAT
   (0x34), TX_ABRT_SOURCE (0x80), TAR (0x04), CON (0x00), ENABLE (0x6C),
   ENABLE_STATUS (0x9C), STATUS (0x70), TXFLR (0x74) and print one decode line.
   Reads only — zero behavior change.
3. In pra_touch_reset_launch, print the same dump after the pra_touch_output_write
   failure (:1076-1080) — the dump must come from inside pra_i2c_xfer (step 2)
   anyway; add nothing after the CLR reads.
4. Optionally extend the charger-style IOMCU read (0152 pattern): map 0xFFD7E000 and
   print raw words +0x00/+0x20/+0x24/+0x28 once, read-only — bit 5 of +0x28 should
   read 0 (deasserted) while the controller answers.
5. Do NOT clear anything new, do NOT retry the transaction, do NOT write
   ENABLE/CON/TAR on this path — one failed transaction, one dump line, exactly the
   sibling-report "zero-cost print first" discipline (rails-research sec 6.1).

## 7. Falsification tests (cheapest first)

1. **Zero-cost (0181 itself)**: the abort dump after the failed BL write.
   - `abrt=0x00000001, flush=13 (0x0D)` ⇒ bit 0 only: address byte clocked out on an
     idle-high bus and every queued command flushed — wrong-address OR silent IC
     (unpowered pads held high by pull-ups). Falsifies the bus-stuck and
     controller-wedge hypotheses; rails are already proven on (0180), so the
     remaining candidates are IC-side mode (bootloader/deep-sleep timing) vs the
     address itself.
   - `abrt=0x00000008, flush<13` ⇒ bit 3 data NACK: the IC ACKed 0x1C and NACKed
     payload — IC alive and launched/rejecting; check which byte via 13-flush.
   - `abrt=0x00001000` (bit 12) ⇒ ARB_LOST: we lost the bus mid-byte — SDA held low
     by something else (clamp/short/another master) — NOT an address problem.
   - `abrt=0x00000200` (bit 9) or bits 8/10 ⇒ restart-family abort: our CON/TAR got
     corrupted (RESTART_EN lost, special bits in TAR, or HS code sent) — a
     config-loss bug in our driver or charger interleaving, not the IC.
   - `abrt=0x00000000` with TX_ABRT pending ⇒ flush count in [31:23] only — count
     the flushed commands; an all-zero source with a pending abort is itself
     diagnostic (TX_FLUSH_CNT-only abort = the "no source" corner).
2. **Liveness re-proof in the same line**: print COMP_VERSION/COMP_TYPE again in the
   dump. Values 3132302a/44570140 ⇒ controller live, not IOMCU-reset, not clock-dead
   (a dead clock reads as SES external abort — PRA-LX1-noted.md:1611 — which would
   have panicked the probe, not returned err=6). If they now read 0/FFFFFFFF or
   abort, the wedge happened between probe and transaction (new failure class).
3. **TAR/CON readback in the dump**: TAR must read 0x0000001C and CON 0x00000063.
   TAR != 0x1C ⇒ the write-while-disabled sequence didn't take (or the charger
   re-owned between setup and xfer — the mutex path, pra_touch.c:539-560).
   CON == 0x65 ⇒ the charger's config survived (owner-tag bug); CON == 0x00/0x06 ⇒
   controller disabled mid-transaction (ENABLE_STATUS.IC_EN==0 confirms).
4. **IOMCU reset status** (optional, one map + 4 reads): readl(0xFFD7E028) bit 5
   must be 0 (deasserted, per the fork's status-poll semantics, hisi:149-153). Bit 5
   = 1 while COMP_VERSION still reads ⇒ the reset line is asserted but the APB
   window is still alive — would falsify the assumption that IOMCU reset kills
   register access (currently UNKNOWN, only the CRG-gate case is evidenced).
5. **Anti-test**: any boot where the dump shows bit 0 set AND rails verified ON AND
   TAR==0x1C AND a second identical transaction also bit 0 ⇒ "silent IC at 0x1C on a
   healthy bus" is confirmed; the next rung moves to IC-side recovery (re-reset +
   longer app-launch budget / single-byte-address read fallback), NOT more
   controller diagnostics.

## 8. Confidence labels

- **VERIFIED** (source file + line on this silicon or its exact IP): full register
  map incl. TX_ABRT_SOURCE 0x80 (Linux v6.1 core.h:46-84 + fork core.c:40-80);
  COMP_TYPE 0x44570140 and our observed reads (core.h:84 + PRA-LX1-noted.md:
  1609-1610); COMP_VERSION decode rule "111*"==v1.11* ⇒ ours = v1.20* (master header
  :43 + arithmetic); ABRT bits 0-15 + fork's 6/8/16 (v6.1 core.h:145-173,
  common.c:31-60, fork core.c:127-196); bit-9 stickiness + clearing rule + TX_FLUSH_CNT
  [31:23] (RP2040 :1908-1918, :1924-1936, :2074-2095); TAR/CON write-only-when-
  disabled (RP2040 :293-296, :93-96); SPEED field [2:1] 1/2/3 (RP2040 :255-268,
  v6.1 :29-32); STOP bit 9 used on this silicon (fork core.c:599-623; v6.1
  master.c:428-435); ABRT_SOURCE-before-CLR_TX_ABRT order (v6.1 master.c:687-694 +
  fork core.c:1005-1011); abort flushes FIFOs (v6.1 master.c:737-740 + fork
  :1056-1059 + RP2040 RXFLR :1834-1837); __i2c_dw_disable ENABLE_STATUS poll
  (common.c:439-463); fork driver identity/probe-message map (hisi:1154 + dmesg.txt
  :892-907); IOMCU reset tuple semantics 0x20/0x24/0x28/bit5 (hisi_6250_i2c.dtsi:31
  + hisi:126-156,875-893); clk_gate_i2c2 = fixed-factor (no gate) vs i2c4 real gate
  (clock dtsi:3024-3031 vs :2107-2114); FIFO 64/64 (dmesg.txt:901 + hisi:969-975);
  ffd73000 absent from live/iomem.txt (:75-79 grep); pra_touch.c define inventory +
  missing 0x80 (:156-169 + grep).
- **INFERRED**: TX_ABRT_SOURCE also clears on ENABLE 1→0 (databook preface quote,
  consistent with fork/upstream flow); SPKLEN presence on v1.20* (fork writes it);
  iomem.txt absence due to no request_mem_region (hisi:853); stock EMUI driver =
  lineage-20 dump + i2c_bus_numb addition (all other prints match); COMP_PARAM_1
  ≈ 0x3F3F____ on our silicon (from the 64/64 print); i2c-0 numbering via
  i2c_bus_numb=0; pad-offset route for SDA/SCL idle levels (UDP pin dtsi gpio187/
  gpio188 = pmx0 0x024/0x028, func 0x1 — raw read useful, input-bit decode UNKNOWN).
- **UNKNOWN**: ABRT_SDA_STUCK_AT_LOW (bit 17) presence on v1.20* (databook quote
  only; fork doesn't define it); the actual SDA/SCL idle levels and pull-up rail on
  the PRA board; IOMCU-reset vs CRG-gate read behavior difference (SES precedent is
  CRG-only); why the PRA product dts sets clock-rate 19200000 while the gate chain
  yields 128 MHz (PRA dts not in the local tree); the TT5's state at the failed
  launch (the very question 0181's dump answers).

Key files: /home/kamion008/Ai/ios/ios-pra/work/ci181/post0180/xnu/bsd/dev/pra_touch.c;
/home/kamion008/Ai/ios/ios-pra/xnu/patches/{0152-pra-charger.patch,0172-pra-touch-probe.patch};
/home/kamion008/Ai/ios/ios-pra/live/{dmesg.txt,iomem.txt}; /home/kamion008/Ai/ios/ios-pra/PRA-LX1-noted.md;
/home/kamion008/Ai/huawei/hi6250-kernel/arch/arm64/boot/dts/auto-generate/{config,overlay}/hi6250/
{hisi_6250_i2c.dtsi,hisi_6250_clock.dtsi,hi6250_udp_default_config.dtsi,hi6250_udp_default_pin.dtsi,hi6250_emulator_config.dts};
github.com/torvalds/linux v6.1 drivers/i2c/busses/{i2c-designware-core.h,i2c-designware-master.c,i2c-designware-common.c} (+ master-branch core.h);
github.com/hisi-oss/android_kernel_huawei_hi6250-8 lineage-20 drivers/i2c/busses/{hisi_i2c_designware.c,i2c-designware-core.c,i2c-designware-core.h};
github.com/raspberrypi/pico-sdk src/rp2040/hardware_regs/include/hardware/regs/i2c.h (fetched copies in /tmp/i2c-research/).

## 9. 0181 design implication

After every failed transaction in the reset/launch path, BEFORE the existing
read-to-clear at pra_touch.c:520 (which erases the evidence), read and print in one
line: RAW_INTR_STAT (0x34, expect bit 6 pending), **IC_TX_ABRT_SOURCE (0x80)**,
IC_TAR (0x04, must be 0x1C), IC_CON (0x00, must be 0x63), IC_ENABLE (0x6C),
IC_ENABLE_STATUS (0x9C bit 0), IC_STATUS (0x70), IC_TXFLR (0x74), plus COMP_VERSION
(0xF8)/COMP_TYPE (0xFC) as the liveness re-proof, and decode ABRT_SOURCE with the
embedded table: b0 ABRT_7B_ADDR_NOACK ("addr NACK"), b3 TXDATA_NOACK, b12 ARB_LOST,
b11 MASTER_DIS, b9 SBYTE_NORSTRT (sticky), b10/b8 restart-disabled variants, b16
USER_ABRT, bits[31:23] TX_FLUSH_CNT (=13/0x0D when the whole 13-byte BL frame was
flushed at address time; smaller = bytes already sent, locates the failing byte).
Ordering is mandatory: **ABRT_SOURCE (0x80) read FIRST, CLR_TX_ABRT (0x54) read
AFTER** — upstream reads-and-preserves the source before the read-to-clear with the
exact comment "The IC_TX_ABRT_SOURCE register is cleared whenever the IC_CLR_TX_ABRT
is read. Preserve it beforehand" (i2c-designware-master.c:687-694; the Huawei fork
duplicates it at core.c:1005-1011), and bit 9 additionally survives every clear
unless its source is fixed (RP2040 i2c.h:2074-2095). No new writes anywhere: the
dump is pure MMIO reads wrapped around the existing ENXIO/ETIMEDOUT exits, so a boot
with pratouchreset=1 produces the same transaction sequence plus one decode line —
and `abrt=0x00000001 flush=0x0D` with TAR==0x1C on a re-proven-live controller
falsifies the controller-side hypotheses outright, narrowing the err=6 to a silent
IC at 0x1C (mode/timing) or a bus-level clamp (which bit 12 would have exposed).

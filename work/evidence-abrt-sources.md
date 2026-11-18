# The abort-bit numeric assignments, quoted from the fetched sources
# (fetched to /tmp/i2c-research during the research; verified first-hand
#  in this session against the report's decode table)

## Linux v6.1 drivers/i2c/busses/i2c-designware-core.h (torvalds/linux tag v6.1)
 * Hardware abort codes from the DW_IC_TX_ABRT_SOURCE register
 *
 * Only expected abort codes are listed here
 * refer to the datasheet for the full list
 */
#define ABRT_7B_ADDR_NOACK	0
#define ABRT_10ADDR1_NOACK	1
#define ABRT_10ADDR2_NOACK	2
#define ABRT_TXDATA_NOACK	3
#define ABRT_GCALL_NOACK	4
#define ABRT_GCALL_READ		5
#define ABRT_SBYTE_ACKDET	7
#define ABRT_SBYTE_NORSTRT	9
#define ABRT_10B_RD_NORSTRT	10
#define ABRT_MASTER_DIS		11
#define ARB_LOST		12
#define ABRT_SLAVE_FLUSH_TXFIFO	13
#define ABRT_SLAVE_ARBLOST	14
#define ABRT_SLAVE_RD_INTX	15

#define DW_IC_TX_ABRT_7B_ADDR_NOACK		BIT(ABRT_7B_ADDR_NOACK)

## Huawei i2c_designware-hs fork i2c-designware-core.c (hisi-oss/android_kernel_huawei_hi6250-8, lineage-20)
#define ABRT_7B_ADDR_NOACK	0
#define ABRT_10ADDR1_NOACK	1
#define ABRT_10ADDR2_NOACK	2
#define ABRT_TXDATA_NOACK	3
#define ABRT_GCALL_NOACK	4
#define ABRT_GCALL_READ		5
#if defined CONFIG_HISI_I2C_DESIGNWARE
#define ABRT_HS_ACKDET		6
#endif
#define ABRT_SBYTE_ACKDET	7
#if defined CONFIG_HISI_I2C_DESIGNWARE
#define ABRT_HS_NORSTRT		8
#endif
#define ABRT_SBYTE_NORSTRT	9
#define ABRT_10B_RD_NORSTRT	10
#define ABRT_MASTER_DIS		11
#define ARB_LOST		12
#if defined CONFIG_HISI_I2C_DESIGNWARE
#define ABRT_USER_ABRT		16
#endif

#define DW_IC_TX_ABRT_7B_ADDR_NOACK	(1UL << ABRT_7B_ADDR_NOACK)

## RP2040 pico-sdk hardware/regs/i2c.h (the licensed DW_apb_i2c RTL register doc)
1933:#define I2C_IC_TX_ABRT_SOURCE_TX_FLUSH_CNT_BITS   _u(0xff800000)
1935:#define I2C_IC_TX_ABRT_SOURCE_TX_FLUSH_CNT_LSB    _u(23)
1948:#define I2C_IC_TX_ABRT_SOURCE_ABRT_USER_ABRT_BITS   _u(0x00010000)
1950:#define I2C_IC_TX_ABRT_SOURCE_ABRT_USER_ABRT_LSB    _u(16)

## RP2040 i2c.h :1908-1910 (the register preamble, verbatim)
//               This register has 32 bits that indicate the source of the
//               TX_ABRT bit. Except for Bit 9, this register is cleared
//               whenever the IC_CLR_TX_ABRT register or the IC_CLR_INTR
//               register is read. To clear Bit 9, the source of the
//               ABRT_SBYTE_NORSTRT must be fixed first; RESTART must be enabled

## RP2040 i2c.h :1924-1936 (the TX_FLUSH_CNT field, verbatim)
// Field       : I2C_IC_TX_ABRT_SOURCE_TX_FLUSH_CNT
// Description : This field indicates the number of Tx FIFO Data Commands which
//               are flushed due to TX_ABRT interrupt. It is cleared whenever
//               I2C is disabled.
//
//               Reset value: 0x0
//
//               Role of DW_apb_i2c:  Master-Transmitter or Slave-Transmitter
#define I2C_IC_TX_ABRT_SOURCE_TX_FLUSH_CNT_RESET  _u(0x000)
#define I2C_IC_TX_ABRT_SOURCE_TX_FLUSH_CNT_BITS   _u(0xff800000)
#define I2C_IC_TX_ABRT_SOURCE_TX_FLUSH_CNT_MSB    _u(31)
#define I2C_IC_TX_ABRT_SOURCE_TX_FLUSH_CNT_LSB    _u(23)
#define I2C_IC_TX_ABRT_SOURCE_TX_FLUSH_CNT_ACCESS "RO"

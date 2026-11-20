# Evidence 1 - boot T11: the touch lines (work/ring52-fresh.txt; ring52 sha256 65e704f4..., fresh [512, 252416) = 251,904 B = 246.0 KiB, 5,507 lines)
```
PRA touch: i2c ffd73000 COMP_VERSION=3132302a COMP_TYPE=44570140
PRA touch: irq gpio28.0 dat=0 dir=0 idle=0
PRA touch: iomcu reset pulsed, status=888453de
PRA touch: rails raw: vbus=00000002 ldo4=00000003 ldo17=00000000
PRA touch: rails vset: ldo4=00000003 ldo17=00000002
PRA touch: rails on: VDDIO VCI enabled, 20 ms ramp
PRA touch: i2c pads: pull-up experiment, sdacfg=00000001 sclcfg=00000001
PRA touch: i2c pads: sda=00000000 scl=00000000 sdacfg=00000001 sclcfg=00000001
PRA touch: i2c pads muxed to I2C func, readback sda=00000001 scl=00000001
PRA touch: reset gpio18.1 done dir=2 dat=2 (the line idles HIGH)
PRA i2c scan: 1 ACK, 111 clean NACK, 0 anomalies, 0 wedged of 112: [1c]
PRA touch: BL_LAUNCH_APP sent crc=0xc720
PRA touch: desc attempt 1: request...
PRA touch: desc attempt 1 failed err=60
PRA touch: desc attempt 2: request...
PRA touch: desc attempt 2 failed err=60
PRA touch: HID desc read failed err=60 (bus timeout); irq polling continues
PRA i2c: hid_desc err=60 abrt=00000000 tar=0000001c/1c con=00000063 en=01 enstat=01 stat=06 flush=0 ver=3132302a type=44570140 abrt=none
PRA touch: probe done, 10 ms poll worker started
PRA touch: irq lo/hi=1000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
PRA touch: irq lo/hi=2000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
```

# Evidence 2 - the vendor IRQ registration (work/rvr/cyttsp5/cyttsp5_core.c:6705-6736)
```
static int cyttsp5_setup_irq_gpio(struct cyttsp5_core_data *cd)
{
	struct device *dev = cd->dev;
	unsigned long irq_flags;
	int rc;

	/* Initialize IRQ */
	cd->irq = gpio_to_irq(cd->cpdata->irq_gpio);
	if (cd->irq < 0) {
		TS_LOG_ERR("%s: error irq:%d\n", __func__, cd->irq);
		return -EINVAL;
	}

	cd->irq_enabled = true;

	TS_LOG_DEBUG("%s: initialize threaded irq=%d\n", __func__, cd->irq);
	if (cd->cpdata->level_irq_udelay > 0) {
		/* use level triggered interrupts */
		irq_flags = IRQF_TRIGGER_LOW | IRQF_ONESHOT;
	} else {
		/* use edge triggered interrupts */
		irq_flags = IRQF_TRIGGER_FALLING | IRQF_ONESHOT;
	}

	if (cd->easy_wakeup_supported_gestures) {
		irq_flags |= IRQF_NO_SUSPEND;
	}

	rc = request_threaded_irq(cd->irq, NULL, cyttsp5_irq, irq_flags,
				  dev_name(dev), cd);
	if (rc < 0) {
		TS_LOG_ERR("%s: Error, could not request irq, rc = %d\n",
```

# Evidence 3 - the PRA fdt touch node (research/pra-artifacts/twrp-golden/fdt.bin)
```
/amba/i2c@FFD73000/cypress_touchscreen@1C/cy,core
    cy,id                        6d61696e5f747473705f636f726500
    cy,name                      637974747370355f636f726500
    cy,irq_gpio                  00000068 00000000 00000000
    cy,rst_gpio                  00000069 00000001 00000000
    cy,hid_desc_register         00000001
    cy,product_name              70726167756500
    cy,support_chip_name         43595454323134303300
    cy,fw_uptate_logic           00000001
    cy,ttda_cap_test_enable      00000001
    cy,dmd_noise_report_enable   00000001
    cy,fw_update_retry_enbale    00000001
    cy,flags                     00000001
    cy,easy_wakeup_supported_gestures 00000f81
    cy,easy_wakeup_gesture_keys  0000003b 0000003c 0000003d 0000003e 0000003f 00000040 00000041 00000042 00000043 00000044 00000057 00000058
    cy,double_tap_enabled        00000001
    cy,dtz_x0                    00000074
    cy,dtz_y0                    00000074
    cy,dtz_x1                    0000025c
    cy,dtz_y1                    0000048c
    cy,upgrade_ttconfig          00000001
    cy,mmi_test_support          00000000
    cy,sleep_fail_retry          00000001
--- phandle map:
00000068 /amba/gpio@fff1d000
00000069 /amba/gpio@e8a1d000
```

# Evidence 4 - the post-0187 driver source (work/ci188/pre0188/xnu/bsd/dev/pra_touch.c:720-805)
```
}

/* 0187: the INT wait - the TT5 signals the response on its INT
 * line (gpio28.0, the pad the worker already histograms). The
 * vendor waits on the wait queue for the descriptor timeout
 * class (cyttsp5_core.c:2988-2994); we poll the pad level for a
 * CHANGE from the probe-sampled idle (the polarity UNKNOWN -
 * either direction counts), bounded ~200 ms in 5 ms tsleep
 * ticks. Called OUTSIDE the bus mutex (between the txns). */
static unsigned pra_touch_ms_ticks(unsigned ms);   /* defined later */

static int
pra_touch_desc_wait_int(void)
{
	unsigned waited = 0;

	while (waited < 200u) {
		uint32_t dat = pra_touch_rd32(pra_gpio_regs,
			    PRA_TOUCH_IRQ_DAT_OFF) & PRA_TOUCH_IRQ_BIT;
		if ((int)(dat ? 1u : 0u) != idle_level) {
			return 0;   /* the line changed: the response is ready */
		}
		(void)tsleep(&pra_touch_chan, PZERO, "pradescw",
			    pra_touch_ms_ticks(5u));
		waited += 5u;
	}
	return ETIMEDOUT;
}

/* 0187: the ASYNCHRONOUS descriptor read - the TT5 is a
 * command/response device, not a register file (the vendor:
 * cyttsp5_core.c:2968-3010 writes the request, waits for the
 * INT, and reads the response via the default pointer;
 * cyttsp5_i2c.c:175+ read_default_nosize = addr+R with NO
 * register write). Our synchronous write-pointer+read returned
 * the IC's fixed default-read state block (boots T9/T10: the
 * ~28 identical bytes across forms). The sequence, issued
 * TWICE (the BL_LAUNCH's reset_expected = 1 - cyttsp5_core.c
 * :2864-2867: the IC resets itself after the launch, so the
 * second attempt survives the reset window): (1) the request
 * [0x01 0x00] with STOP; (2) the INT wait; (3) the PURE read -
 * pra_touch_txn(NULL, 0, desc, 32): the 0185 interleaved phase
 * pushes the CMD_READs and drains (the 0183 scan's 1-byte pure
 * read already ACKed on this bus). */
static int
pra_touch_desc_read(uint8_t *desc)
{
	uint8_t req[2] = { 0x01u, 0x00u };
	int error = 0;
	int attempt;

	for (attempt = 0; attempt < 2; attempt++) {
		printf("PRA touch: desc attempt %d: request...\n",
			    attempt + 1);
		error = pra_touch_txn(req, 2, NULL, 0);
		if (error == 0) {
			error = pra_touch_desc_wait_int();
		}
		if (error == 0) {
			error = pra_touch_txn(NULL, 0, desc, HID_DESC_SIZE);
		}
		if (error == 0) {
			printf("PRA touch: desc attempt %d: the response ",
				"received (%u bytes)\n", attempt + 1,
					    (unsigned)HID_DESC_SIZE);
			return 0;
		}
		printf("PRA touch: desc attempt %d failed err=%d\n",
			    attempt + 1, error);
	}
	return error;
}

/*
 * Input report read, mainline cyttsp5_read semantics (cyttsp5.c:218-238):
 * first a 2-byte length read from the input register; 0 or 2 means
 * nothing pending. Otherwise re-read the register for the whole report -
 * the second read includes the 2 length bytes (mainline re-parses them at
 * :706 after the full read). Oversize reports are refused, never drained
 * blind.
 */
static int
pra_touch_input_read(uint8_t *buf, unsigned *lenp)
{
	uint8_t reg[2] = {
		(uint8_t)(input_reg & 0xffu),
```

# Evidence 5 - the patch + the generator verify
```
-rw-r--r-- 1 kamion008 kamion008 8459 20 nov 17.23 xnu/patches/0188-pra-touch-int-level.patch
  [2] the unconditional read: replaced @ line 764
  [3] the framing trail: replaced @ line 1793
[verify] git apply --check rc=0
[verify] GNU patch --fuzz=0 --dry-run rc=0
[verify] git apply rc=0
[verify] pra_touch.c: applied == expected
[verify] the wait helper @742 < desc_read @776 < the worker @1815
[verify] structural assertions PASS (order, txn counts, ungated read, braces)
[done] VERIFY PASS: 0188 applies to the reconstructed post-0187 base
```

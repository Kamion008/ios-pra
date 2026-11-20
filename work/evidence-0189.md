# Evidence 1 - boot T12: the touch lines (work/ring53-fresh.txt; ring53 sha256 eb7a9208..., fresh [512, 252032) = 251,529 B / 5,496 lines)
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
PRA touch: desc attempt 118017742: the response PRA touch: HID desc len=0 bcd=0x76d2 rid=0x5a87 in=0xe2fd out=0x139d cmd=0xd6af data=0xbbf5 vid=0xb557 pid=0xfd73 ver=0x74ab (err=0)
PRA touch: descriptor invalid (len=0 bcd=0x76d2), touch reads disabled
PRA touch: desc raw=00 00 58 1e d2 76 7d f7 87 5a fd e2 95 e6 9d 13
PRA touch: probe done, 10 ms poll worker started
...
PRA touch: irq lo/hi=1000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
PRA touch: irq lo/hi=2000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
```
The attempt line's `118017742` = the low 32 bits of the pointer to the
string literal `"received (%u bytes), irq %u->%u%s\n"` (the 0188
printf's second literal was passed as an argument). The read itself
ran: err=0, 32 bytes, buffer starting `00 00`.

# Evidence 2 - the vendor descriptor path (work/rvr/cyttsp5/cyttsp5_core.c:2968-3030)
```c
static int cyttsp5_get_hid_descriptor_(struct cyttsp5_core_data *cd,
				       struct cyttsp5_hid_desc *desc)
{
	...
	cd->hid_cmd_state = 1;
	...
	memcpy(cmd, &cd->hid_core.hid_desc_register,
	       sizeof(cd->hid_core.hid_desc_register));

	rc = cyttsp5_adap_write_read_specific(cd, 2, cmd, NULL);
	...
	t = wait_event_timeout(cd->wait_q, (cd->hid_cmd_state == 0),
			       msecs_to_jiffies
			       (CY_HID_GET_HID_DESCRIPTOR_TIMEOUT));
	if (IS_TMO(t)) { ... rc = -ETIME; goto error; }

	memcpy((u8 *) desc, cd->response_buf, sizeof(struct cyttsp5_hid_desc));

	if (le16_to_cpu(desc->hid_desc_len) != sizeof(*desc) ||
	    le16_to_cpu(desc->bcd_version) != CY_HID_VERSION) {
		TS_LOG_ERR("%s: Unsupported HID version\n", __func__);
		return -ENOSYS;
	}
```
Readiness = the INT transition (hid_cmd_state, set to 0 by the IRQ
handler); the response buffer is filled by the IRQ-side read.

# Evidence 3 - the vendor response read (work/rvr/cyttsp5/cyttsp5_i2c.c:175-250)
```c
static int cyttsp5_i2c_read_default_nosize(struct device *dev, u8 *buf, u32 max)
{
	...
	msgs[0].addr = client->addr;
	msgs[0].flags = (client->flags & I2C_M_TEN) | I2C_M_RD;
	msgs[0].len = 2;
	msgs[0].buf = buf;
	rc = i2c_transfer(client->adapter, msgs, msg_count);
	...
	size = get_unaligned_le16(&buf[0]);
	if (!size || size == 2) {
		return 0;                     /* nothing pending */
	}
	if (size > max) {
		return -EINVAL;
	}

	rc = i2c_master_recv(client, buf, size);
	...
	if (rc < 0) { ... return rc; } else if (rc != size) { ... return -EIO; }
	return 0;
}
```
The 2-byte read is a PURE read (no register write); the payload read
overwrites the same buffer from offset 0. The descriptor's own first
field `hid_desc_len` is 32 (= 0x20), the same value as the length
word, and the vendor checks exactly that field at offset 0.

# Evidence 4 - the PRA fdt touch node (research/pra-artifacts/twrp-golden/fdt.bin)
```
/amba/i2c@FFD73000/cypress_touchscreen@1C/cy,core
    cy,hid_desc_register         00000001
```
The request bytes `[01 00]` are this register, little-endian.

# Evidence 5 - the post-0188 driver source (work/ci189/pre0189/xnu/bsd/dev/pra_touch.c:764-814)
```c
		printf("PRA touch: desc attempt %d: the response ",
			"received (%u bytes), irq %u->%u%s\n",
			    attempt + 1, (unsigned)HID_DESC_SIZE,
			    irq_start, irq_end, wait_error ?
			    ", read past a wait timeout" : "");
		return 0;
```
(the 0188 argument bug: the second literal is an argument). The 0188
level wait returns 0 immediately while the pad is LOW; the pure read
then runs ungated on the wait outcome.

# Evidence 6 - the patch + the generator verify
```
[verify] git apply --check rc=0
[verify] GNU patch --fuzz=0 --dry-run rc=0
[verify] git apply rc=0
[verify] pra_touch.c: applied == expected
[verify] order: wait < desc_read < worker
[verify] structural assertions PASS (length poll, hlen gate, raw 32, braces)
[done] VERIFY PASS: 0189 applies to the reconstructed post-0188 base
```
The base: work/ci189/pre0189 = a copy of work/ci188/pre0188 (the
post-0186 reconstruction + 0187) + the 0188 patch applied inside
pre0189/xnu (markers: 4 `PRA touch: desc attempt`, 1 `desc raw=`).

# Evidence 7 - the new function (excerpt from the emitted patch)
```c
		error = pra_touch_txn(req, 2, NULL, 0);
		if (error == 0) {
			waited = 1;
			wait_error = pra_touch_desc_wait_int(&irq_start, &irq_end);
			for (waited_ms = 0; waited_ms < 200u; waited_ms += 5u) {
				error = pra_touch_txn(NULL, 0, lenb, 2);
				if (error) break;
				hlen = pra_touch_le16(lenb);
				if (hlen != 0 && hlen != 2) break;
				(void)tsleep(&pra_touch_chan, PZERO, "pradescl",
				    pra_touch_ms_ticks(5u));
			}
			if (error == 0 && hlen != 0 && hlen != 2 &&
			    hlen > HID_DESC_SIZE) {
				printf("PRA touch: desc attempt %d: "
				    "oversize response hdr=%#x\n",
				    attempt + 1, hlen);
				error = EIO;
			}
		}
		if (error == 0 && hlen != 0 && hlen != 2) {
			memset(desc, 0, HID_DESC_SIZE);
			error = pra_touch_txn(NULL, 0, desc, hlen);
		}
```

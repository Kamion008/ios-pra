# Evidence 1 - boot T13, the touch block (work/ring54-fresh.txt; ring54 sha256 2c57729c..., fresh [512, 161280) = 160,768 B / 2,795 lines)
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
PRA touch: desc attempt 1: the response received (32 bytes, hdr=0x20), irq 0->0
PRA touch: HID desc len=32 bcd=0x100 rid=0x2 in=0x3 out=0x4 cmd=0x5 data=0x6 vid=0x4b4 pid=0xc101 ver=0x100 (err=0)
PRA touch: app mode confirmed, input reg 0x3 max_input=254
PRA touch: probe done, 10 ms poll worker started
...
PRA touch: irq lo/hi=1000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
PRA touch: irq lo/hi=2000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
...
PRA touch: hid inject slot=0 down x=588 y=1878
SWEET HID: touch 0 down at 588,1878 edge
PRA touch: irq lo/hi=57500/0 idle=0 reports=1 errs=0 corrupt=0 last: slot=0 x=588 y=1878 p=186
...
SWEET HID: touch 0 up at 653,1165 edge
SWEET HID: touch 0 down at 1039,1856 edge
...
SWEET HID: touch 1 down at 375,546
SWEET HID: touch 1 up at 375,546
PRA touch: irq lo/hi=58500/0 idle=0 reports=9 errs=1 corrupt=0 last: slot=0 x=528 y=1892 p=105
PRA touch: irq lo/hi=60500/0 idle=0 reports=29 errs=1 corrupt=0 last: slot=0 x=686 y=1279 p=252
PRA touch: irq lo/hi=61500/0 idle=0 reports=38 errs=1 corrupt=0 last: slot=0 x=731 y=548 p=252
SWEET HID: touch 0 up at 731,548 edge
SWEET HID: touch 1 down at 993,1153
SWEET HID: touch 0 down at 502,1858
SWEET HID: touch 1 up at 993,1153
PRA touch: irq lo/hi=62500/0 idle=0 reports=42 errs=1 corrupt=0 last: slot=0 x=1037 y=1882 p=132
```
The 57500/58500/... ticks = 575-625 s at 10 ms; 42 reports in
~50 s = ~0.8 Hz. The pad histogram is LOW for every sample (hi=0).

# Evidence 2 - the post-0189 worker source (work/ci190/post0189/xnu/bsd/dev/pra_touch.c:1113-1131)
```c
		/*
		 * Reads happen when the line differs from the level sampled
		 * at probe (polarity UNKNOWN - both levels are histogrammed
		 * so the boot log fixes it), plus a 1 Hz heartbeat so a dead
		 * or muxed-away IRQ line cannot wedge the driver silently
		 * (pra-touch-plan.md rung 3). Every error backs reads off
		 * for 1 s, so a stuck line with a dead bus costs at most a
		 * handful of bounded transactions per second.
		 */
		do_read = false;
		if (pra_live && input_reg != 0) {
			if ((uint32_t)idle_level != level) {
				do_read = true;
			} else if (loops - last_heartbeat >= loops_per_1s) {
				do_read = true;
				last_heartbeat = loops;
			}
		}
```
The histogram above the gate (same file):
```c
		if (level) {
			irq_hi++;
		} else {
			irq_lo++;
		}
```
`loops_per_1s` is not dead state after this patch: it still feeds
`loops_per_10s = loops_per_1s * PRA_TOUCH_PRINT_S;` (the 10 s stats
cadence) and `backoff = (unsigned)loops_per_1s;` (the 1 s error
backoff).

`idle_level` is sampled at probe (T13: `irq gpio28.0 ... idle=0`),
and `level` is 0 for every sample, so the first branch is dead.

# Evidence 3 - the read the poll repeats (pra_touch.c:818-847 and the vendor model)
```c
static int
pra_touch_input_read(uint8_t *buf, unsigned *lenp)
{
	uint8_t reg[2] = {
		(uint8_t)(input_reg & 0xffu),
		(uint8_t)(input_reg >> 8),
	};
	uint8_t lenb[2];
	uint32_t size;
	int error;

	error = pra_touch_txn(reg, 2, lenb, 2);
	if (error) {
		return error;
	}
	size = pra_touch_le16(lenb);
	if (size == 0 || size == 2) {
		*lenp = 0;              /* nothing pending */
		return 0;
	}
	if (size < TOUCH_MIN_REPORT || size > report_cap) {
		return EIO;             /* counted, skipped */
	}
	error = pra_touch_txn(reg, 2, buf, size);
	if (!error) {
		*lenp = (unsigned)size;
	}
	return error;
}
```
The polling txn and the mutex (same file):
```c
static int
pra_touch_txn(const uint8_t *wr, unsigned wlen, uint8_t *rd, unsigned rlen)
{
	bool reowned;
	int error;

	if (!pra_touch_bus_on) {
		return pra_i2c_xfer(wr, wlen, rd, rlen);
	}
	reowned = pra_i2c_bus_take(PRA_BUS_TOUCH);
	...
	error = pra_i2c_xfer(wr, wlen, rd, rlen);
	pra_i2c_bus_drop();
	return error;
}
```
The worker's `tsleep` sits at the TOP of the loop (evidence 2:
`(void)tsleep(&pra_touch_chan, PZERO, "pratch", tick);`), before the
txn - no mutex is held between ticks.

Mainline `cyttsp5_read` (cyttsp5.c:218-238): the same 2-byte length
read, 0/2 = nothing pending, then the whole report; the vendor calls
it from the IRQ path at the panel's report rate, not on a timer.
The 0189 descriptor poll already ran `pra_touch_txn(NULL, 0, lenb, 2)`
every 5 ms for up to 200 ms (40 reads) and returned hdr=0x20 on the
first attempt - the per-txn cost is proven at >=200 Hz.

# Evidence 4 - the generator verify (work/gen0190.py run)
```
[emit] wrote .../xnu/patches/0190-pra-touch-input-poll.patch
  [1] last_heartbeat declaration removed: line 1083
  [2] poll_announced declared after line 1084
  [3] comment+gate replaced: lines 1114..1131
[verify] git apply --check rc=0
[verify] GNU patch --fuzz=0 --dry-run rc=0
[verify] git apply rc=0
[verify] pra_touch.c: applied == expected
[verify] structural assertions PASS (every-tick poll, marker, 1 Hz state gone, braces)
[done] VERIFY PASS: 0190 applies to the reconstructed post-0189 base
```
The base: work/ci190/post0189 = a copy of work/ci189/pre0189 (the
mini-repo carrying bsd/dev/pra_touch.c) + the 0189 patch applied with
`git apply` ("Applied patch bsd/dev/pra_touch.c cleanly"). The 0189
marker in the base: `desc attempt 1: ... received (%u bytes, hdr=%#x)`
and the `no response after` line.

# Evidence 5 - the emitted patch (the hunk)
```diff
@@ -1080,9 +1080,9 @@
 {
 	unsigned tick = (unsigned)hz / 100u;
 	uint64_t loops_per_1s, loops_per_10s, loops = 0, last_print = 0;
-	uint64_t last_heartbeat = 0;
 	uint32_t evt_mark, err_mark, corrupt_mark, printed = 0;
 	unsigned backoff = 0;
+	static bool poll_announced;   /* 0190: the poll-mode line once */
@@ -1112,21 +1112,26 @@
 		/*
-		 * Reads happen when the line differs from the level sampled
-		 * at probe (polarity UNKNOWN - both levels are histogrammed
-		 * so the boot log fixes it), plus a 1 Hz heartbeat so a dead
-		 * or muxed-away IRQ line cannot wedge the driver silently
-		 * (pra-touch-plan.md rung 3). Every error backs reads off
-		 * for 1 s, so a stuck line with a dead bus costs at most a
-		 * handful of bounded transactions per second.
+		 * 0190: read EVERY worker tick (10 ms). The pad is stuck
+		 * LOW on this board (T11-T13: irq lo/hi = N/0), so the
+		 * old level-diff gate never fired and the 1 Hz heartbeat
+		 * sampled the panel at ~1 Hz (T13: 42 reports over ~50 s)
+		 * - far too coarse for a gesture. The input read is a
+		 * 2-byte length word, with the payload only when data is
+		 * pending; at 10 ms this is the vendor's IRQ-rate read
+		 * with the stuck INT line replaced by polling. Every
+		 * error still backs reads off for 1 s, so a dead bus
+		 * costs at most a handful of bounded transactions per
+		 * second.
 		 */
 		do_read = false;
 		if (pra_live && input_reg != 0) {
-			if ((uint32_t)idle_level != level) {
-				do_read = true;
-			} else if (loops - last_heartbeat >= loops_per_1s) {
-				do_read = true;
-				last_heartbeat = loops;
+			do_read = true;
+			if (!poll_announced) {
+				poll_announced = true;
+				printf("PRA touch: input poll every %u ms "
+				    "(the INT line is stuck LOW)\n",
+				    (unsigned)((tick * 1000u) / (unsigned)hz));
 			}
 		}
```

# Evidence 6 - the SweetHIDTouch suppression (xnu/patches/0058-sweet-hid-event-services.patch, the SweetHID.cpp body)
```c
	IOLockLock(fLock);
	bool was = fDown[finger];
	IOFixed nx = (IOFixed)(((int64_t)x << 16) / 1080);
	IOFixed ny = (IOFixed)(((int64_t)y << 16) / 2400);
	bool moved = down && (nx != fX[finger] || ny != fY[finger]);
	if (was == down && !moved) {
		IOLockUnlock(fLock);
		return;
	}
	...
	IOLockUnlock(fLock);

	if (was != down) {
		IOLog("SWEET HID: touch %d %s at %d,%d%s\n", ...);
	}
	dispatchEvent(collection);
	collection->release();
```
A re-served identical down report returns before any event is
dispatched.

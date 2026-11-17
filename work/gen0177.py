#!/usr/bin/env python3
"""gen0177.py - build xnu/patches/0177-pra-touch-hid.patch.

0177: the full PRA touch driver on top of the 0172 read-only probe.

- Rung A (boot-arg pratouchreset=1, OFF by default): readback-verified XRES
  toggle of gpio18.1 (gpio145, bank @0xE8A1D000), the 11-byte BL_LAUNCH_APP
  frame to output register 0x0004 (mainline cyttsp5.c:609-626, CRC-ITU-T
  init 0xFFFF over bytes [4..7]), bounded waits, then the descriptor
  re-read reports the outcome. Also fixes a latent 0172 bug (pra_i2c_setup
  was dead code - pra_tar stayed 0 and every transaction returned ENXIO
  before touching the bus), but ONLY behind the boot-arg, so the
  no-boot-arg path is byte-identical to 0175.
- Rung B: valid TT5 contacts are injected into SweetHIDTouch via
  sweet_hid_touch() (SweetHID.cpp:565-571; donor a5xelte_touch.c pattern)
  with a 10-slot down[] table and release-all on worker error. Gated on
  pra_live: with a dead IC (no boot-arg) the driver is inert.
- Shared i2c2 arbitration with pra_charger.c (WORKLOG sec 3 hazard, sec
  10.4): one bus mutex + owner tag; a taker that finds a foreign owner
  reconfigures the controller before transacting.

Replay lineage (the true sources are the CI-compiled buildtree from run
44119547672, /tmp/bt441-src/xnu):
- bsd/dev/pra_touch.c, bsd/dev/pra_charger.c: taken verbatim from the
  buildtree (post-0176 state; markers verified by the orchestrator).
- The patch is xnu-tree-only (HEAD f851352: a yml hunk inside a patch
  cannot apply in CI's dxb tree and silently skips the whole patch); the
  CI marker asserts are a direct working-tree edit to the repo's
  .github/workflows/xnu.yml, committed by the orchestrator beside the
  patch (same as the 0176 asserts).

All C insertions use TABs (verified with cat -A against the buildtree).
"""
import re, difflib, subprocess, os, tempfile, shutil

REPO = "/home/kamion008/Ai/ios/ios-pra"
BT = "/tmp/bt441-src/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0177-pra-touch-hid.patch"


def read_lines(path):
    return open(path, encoding="utf-8", errors="surrogateescape").read().splitlines()


def sub(lines, old, new, tag):
    """Replace one exact unique block."""
    occ = sum(1 for i in range(len(lines))
              if tuple(lines[i:i + len(old)]) == tuple(old))
    assert occ == 1, f"{tag}: anchor not unique (occ={occ})"
    i = next(i for i in range(len(lines))
             if tuple(lines[i:i + len(old)]) == tuple(old))
    return lines[:i] + new + lines[i + len(old):]


def insert_after(lines, anchor, block, tag):
    return sub(lines, anchor, anchor + block, tag)


def insert_before(lines, anchor, block, tag):
    return sub(lines, anchor, block + anchor, tag)


def parse_hunks(path, want_file):
    txt = open(path, encoding="utf-8", errors="surrogateescape").read().splitlines()
    cur = None; hunks = []
    hdr = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    i = 0
    while i < len(txt):
        l = txt[i]
        if l.startswith("--- a/") or l.startswith("--- /dev/null"):
            m2 = re.match(r"--- a/(\S+)", l); cur = m2.group(1) if m2 else None
        elif l.startswith("@@") and cur == want_file:
            m = hdr.match(l)
            os_, oc = int(m.group(1)), int(m.group(2) or 1)
            ns_, nc = int(m.group(3)), int(m.group(4) or 1)
            body = []; i += 1; a = b = 0
            while i < len(txt) and (a < oc or b < nc):
                bl = txt[i]
                if bl.startswith("@@") or bl.startswith("--- a/") or bl.startswith("diff --git"):
                    break
                body.append(bl)
                if bl.startswith(" "): a += 1; b += 1
                elif bl.startswith("-"): a += 1
                elif bl.startswith("+"): b += 1
                elif bl.startswith("\\"): pass
                else: break
                i += 1
            hunks.append((os_, oc, nc, body)); continue
        i += 1
    return hunks


def apply_hunks(src, hunks, tag):
    delta = 0
    for (os_, oc, nc, body) in hunks:
        old = [l[1:] for l in body if l.startswith((" ", "-"))]
        pos = os_ - 1 + delta
        if not all(src[pos + k].rstrip() == old[k].rstrip() for k in range(oc)):
            found = -1
            for s in range(max(0, pos - 60), min(len(src), pos + 60)):
                if all(src[s + k].rstrip() == old[k].rstrip() for k in range(oc)):
                    found = s; break
            assert found >= 0, f"{tag} hunk @{os_}: context not found"
            pos = found
        new = [l[1:] for l in body if l.startswith((" ", "+"))]
        src = src[:pos] + new + src[pos + oc:]
        delta += nc - oc
    return src


# ======================================================================
# 1. bsd/dev/pra_touch.c  (base = buildtree, post-0176)
# ======================================================================
touch_old = read_lines(f"{BT}/bsd/dev/pra_touch.c")
t = list(touch_old)
n0 = len(t)

# E1: the reset-gpio sentence in the intro is no longer true.
t = sub(t, [
" * hisi_6250_gpio.dtsi:404-406). The reset gpio 145 (gpio18.1 @ 0xE8A1D000)",
" * is NOT driven by this driver: no reset, no output-register writes, no",
" * rail writes - the whole probe is MMIO reads plus two HID-over-I2C read",
" * transaction types (descriptor, input report).",
], [
" * hisi_6250_gpio.dtsi:404-406). The reset gpio 145 (gpio18.1 @ 0xE8A1D000)",
" * is driven ONLY behind boot-arg pratouchreset=1 (0177 rung A: XRES toggle",
" * + BL_LAUNCH_APP; rails are never written at any rung). Without it: no",
" * reset, no output-register writes, no controller writes - the whole",
" * probe is MMIO reads plus the two HID-over-I2C read transaction types",
" * (descriptor, input report), functionally identical to 0172/0175.",
], "E1 intro reset sentence")

# E2: the shared-bus hazard paragraph becomes the 0177 description.
t = sub(t, [
" * Shared-bus hazard (documented, not solved in this draft): the charger",
" * driver (pra_charger.c) configures and reads the SAME controller at",
" * 0xFFD73000 every 10 s with no arbitration between its poll thread and",
" * this driver's worker. A collision corrupts one transaction on one side;",
" * both sides recover bounded (timeout -> re-setup on the next attempt).",
" * Acceptable for a default-off, read-only probe; the shared pra_i2c layer",
" * (pra-touch-plan.md sketch 0162) is the first follow-up before any real",
" * event plumbing.",
], [
" * Shared-bus arbitration (0177): the charger driver (pra_charger.c) drives",
" * the SAME controller at 0xFFD73000 (WORKLOG sec 3 hazard, sec 10.4), so",
" * both drivers now go through one bus mutex with an owner tag (pra_i2c_",
" * bus_take/drop below). A taker that finds a foreign owner reconfigures",
" * the controller for its own client before transacting, so no transaction",
" * can run against another driver's TAR. Without pratouchreset=1 the touch",
" * side never takes the mutex, so the charger's transaction sequence is",
" * unchanged (it now holds the shared mutex around each read/write).",
" *",
" * 0177 rung A (pratouchreset=1, OFF by default; WORKLOG sec 10.3): the",
" * descriptor NACK's root cause is UNKNOWN (touch rail state / deep-sleep",
" * inheritance rank first). Behind the boot-arg the probe attempts the",
" * standard recovery: it toggles gpio18.1 readback-verified, sends the",
" * 11-byte BL_LAUNCH_APP frame to output register 0x0004 (mainline",
" * cyttsp5.c:609-626), sleeps ~200 ms, and the descriptor re-read in the",
" * probe reports the outcome. Fixed tick budgets (~230 ms nominal, tsleep,",
" * no hard upper bound); failures are counted; the probe continues",
" * exactly as without the boot-arg.",
" *",
" * 0177 rung B: valid TT5 touch reports are injected into the live",
" * SweetHIDTouch IOHIDEventService via sweet_hid_touch() (donor",
" * a5xelte_touch.c:527/529 pattern) with per-slot down[] tracking:",
" * present slots are pressed/moved and any still-down slot missing from",
" * the report is released with its last-known coordinates; worker errors",
" * release ALL slots. Gated on pra_live: with a dead IC the injection",
" * code is inert.",
], "E2 header hazard paragraph")

# E3: the sweet_hid_touch extern next to the other externs.
t = insert_after(t, ["extern int hz;"], [
"",
"/* SweetHIDTouch entry point (iokit/Kernel/arm/hid/SweetHID.cpp:565-571). */",
"extern void sweet_hid_touch(int finger, int down, int x, int y);",
], "E3 sweet_hid_touch extern")

# E4: rung A/B defines after the report-read cap.
t = insert_after(t, ["#define PRA_TOUCH_MAX_REPORT    128u"], [
"",
"/*",
" * 0177 rung A: RST gpio 145 = bank gpio18 pin 1 @ 0xE8A1D000 (0172 header",
" * comment; stock dmesg \"reset gpio is 145\", live/dmesg.txt:3875, and",
" * \"cyttsp5_xres: RESET CYTTSP gpio=145\", live/dmesg.txt:4052). pl061",
" * layout like the gpio28 bank above: per-pin DAT slot at bank + pin*4",
" * (level in bit 0), DIR word at bank + 0x400 (bit per pin, 1 = output).",
" * The /pra-touch ADT node carries only the i2c2 and gpio28 windows",
" * (WORKLOG sec 6), so the reset bank is a fixed map. Polarity and pulse",
" * timing follow mainline cyttsp5.c (reset asserted HIGH :873-874, >= 10 us",
" * pulse :881, device-up delay :885-886); the stock vendor toggle details",
" * are UNKNOWN (WORKLOG sec 9), which is why every stage is readback-",
" * verified and any failure just aborts the rung.",
" */",
"#define PRA_TOUCH_RST_BASE      0xE8A1D000ULL",
"#define PRA_TOUCH_RST_SIZE      0x1000u",
"#define PRA_TOUCH_RST_DAT_OFF   (1u * 4u)       /* gpio18.1 */",
"#define PRA_TOUCH_RST_DAT_BIT   0x1u            /* level in bit 0 */",
"#define PRA_TOUCH_RST_DIR_OFF   0x400u",
"#define PRA_TOUCH_RST_DIR_BIT   0x2u            /* pin 1 in the DIR word */",
"",
"/*",
" * BL_LAUNCH_APP output-register frame (mainline cyttsp5.c:34-37,609-623):",
" * u16 11, report id 0x40, reserved 0x00, SOP 0x01, cmd 0x3B, u16 0x0000,",
" * CRC-ITU-T (poly 0x1021, init 0xFFFF) over bytes [4..7], EOP 0x17. The",
" * frame goes to HID_OUTPUT_REG 0x0004 (cyttsp5.c:44) as [reg lo][reg hi]",
" * + payload - the write form WORKLOG sec 3 verified against cyttsp5_write",
" * (:240-263).",
" */",
"#define PRA_TOUCH_OUT_REG       0x0004u",
"#define PRA_TOUCH_BL_LEN        11u",
"",
"/* Shared-bus owner ids for pra_i2c_bus_take() (mirrored in pra_charger.c). */",
"#define PRA_BUS_TOUCH           1",
"#define PRA_BUS_CHARGER         2",
], "E4 rung defines")

# E5: injection + rung state after the worker counters.
t = insert_after(t, [
"static bool have_contact;",
"static int last_contact_slot = -1, last_contact_x = -1;",
"static int last_contact_y = -1, last_contact_p = -1;",
], [
"",
"/* 0177 rung B: injection state, worker-thread only like the counters",
" * above. The tables mirror the donor's a5_touch_active/x/y",
" * (a5xelte_touch.c:484-494,527-529) sized to the 10 TT5 contacts, which",
" * is also SweetHIDTouch's SWEET_TOUCH_FINGERS (SweetHID.cpp:350). */",
"static bool pra_down[MAX_CONTACTS];     /* slots currently reported down */",
"static int pra_last_x[MAX_CONTACTS];    /* last-known coords per slot */",
"static int pra_last_y[MAX_CONTACTS];",
"",
"/* 0177 rung A: boot-arg gate + bus-arbitration state + reset failures. */",
"static bool pra_touch_rst;              /* pratouchreset=1 */",
"static bool pra_touch_bus_on;           /* txn wrapper arbitrates */",
"static uint32_t pra_rst_fail;           /* reset+launch stage failures */",
], "E5 rung state")

# E6: shared bus mutex + exported take/drop after the le16 helper.
t = insert_after(t, [
"static uint32_t",
"pra_touch_le16(const uint8_t *p)",
"{",
"\treturn (uint32_t)p[0] | ((uint32_t)p[1] << 8);",
"}",
], [
"",
"/*",
" * Shared i2c2 arbitration with pra_charger.c (WORKLOG sec 3 hazard, sec",
" * 10.4: mandatory before event plumbing). One mutex serializes every",
" * transaction on the 0xFFD73000 controller; the owner tag remembers who",
" * configured it last, and a taker that finds a foreign owner re-runs its",
" * own setup before transacting. The charger is the boot default owner, so",
" * without pratouchreset=1 (the touch side never takes the mutex) the",
" * charger's transaction sequence is unchanged. Exported: pra_charger.c",
" * declares these two and passes PRA_BUS_CHARGER.",
" *",
" * No sleep runs under this mutex: every transaction body is bounded MMIO",
" * spin polls (pra_i2c_xfer/pra_i2c_setup never tsleep or delay - the",
" * only sleeps in both drivers are the worker ticks and the reset-path",
" * waits, all taken outside the lock). Worst-case hold is ~40 ms on a",
" * dead bus, microseconds on a live one.",
" */",
"static LCK_GRP_DECLARE(pra_bus_grp, \"pra_bus\");",
"static LCK_MTX_DECLARE(pra_bus_lck, &pra_bus_grp);",
"static int pra_bus_owner = PRA_BUS_CHARGER;",
"",
"bool",
"pra_i2c_bus_take(int who)",
"{",
"\tbool reowned;",
"",
"\tlck_mtx_lock(&pra_bus_lck);",
"\treowned = pra_bus_owner != who;",
"\tpra_bus_owner = who;",
"\treturn reowned;",
"}",
"",
"void",
"pra_i2c_bus_drop(void)",
"{",
"\tlck_mtx_unlock(&pra_bus_lck);",
"}",
], "E6 bus mutex + take/drop")

# E7: write-only transaction support in pra_i2c_xfer (STOP on last byte).
t = sub(t, [
"\t\tif (room) {",
"\t\t\tpra_touch_wr32(r, DW_IC_DATA_CMD, wr[pushed++]);",
"\t\t} else if (error == 0) {",
"\t\t\terror = ETIMEDOUT;",
"\t\t}",
], [
"\t\tif (room) {",
"\t\t\tuint32_t cmd = wr[pushed++];",
"",
"\t\t\t/* 0177: write-only transaction (BL frame) - STOP on the",
"\t\t\t * last byte. Read transactions keep the 0172 form: STOP",
"\t\t\t * rides the last read byte. */",
"\t\t\tif (rlen == 0 && pushed == wlen) {",
"\t\t\t\tcmd |= DW_IC_CMD_STOP;",
"\t\t\t}",
"\t\t\tpra_touch_wr32(r, DW_IC_DATA_CMD, cmd);",
"\t\t} else if (error == 0) {",
"\t\t\terror = ETIMEDOUT;",
"\t\t}",
], "E7 xfer write-only STOP")

# E8: the txn wrapper after pra_i2c_xfer.
t = insert_before(t, [
"/* HID descriptor: write the 16-bit LE register address 0x0001, repeated",
" * start, read 32 bytes (see header comment for the addressing source). */",
], [
"/*",
" * The one transaction entry point for the touch side (WORKLOG sec 10.4).",
" * With pra_touch_bus_on (pratouchreset=1) the shared bus mutex is held",
" * across setup+transaction and the controller is reconfigured whenever",
" * the charger touched it last or after a timeout (pra_tar sentinel).",
" * WITHOUT the boot-arg the 0172 path is kept as-is: pra_tar stays 0",
" * (setup is not called), so the descriptor read returns the same ENXIO",
" * as today and nothing is written to the controller.",
" */",
"static int",
"pra_touch_txn(const uint8_t *wr, unsigned wlen, uint8_t *rd, unsigned rlen)",
"{",
"\tbool reowned;",
"\tint error;",
"",
"\tif (!pra_touch_bus_on) {",
"\t\treturn pra_i2c_xfer(wr, wlen, rd, rlen);",
"\t}",
"\treowned = pra_i2c_bus_take(PRA_BUS_TOUCH);",
"\tif (reowned) {",
"\t\tpra_tar = 0;",
"\t}",
"\tif (pra_tar == 0 && pra_i2c_setup()) {",
"\t\tpra_tar = 0;",
"\t\tpra_i2c_bus_drop();",
"\t\treturn ETIMEDOUT;",
"\t}",
"\terror = pra_i2c_xfer(wr, wlen, rd, rlen);",
"\tpra_i2c_bus_drop();",
"\treturn error;",
"}",
"",
], "E8 txn wrapper")

# E9-E11: route all reads through the wrapper.
t = sub(t, ["\treturn pra_i2c_xfer(reg, 2, desc, HID_DESC_SIZE);"],
        ["\treturn pra_touch_txn(reg, 2, desc, HID_DESC_SIZE);"],
        "E9 desc read call")
t = sub(t, ["\terror = pra_i2c_xfer(reg, 2, lenb, 2);"],
        ["\terror = pra_touch_txn(reg, 2, lenb, 2);"],
        "E10 input len read call")
t = sub(t, ["\terror = pra_i2c_xfer(reg, 2, buf, size);"],
        ["\terror = pra_touch_txn(reg, 2, buf, size);"],
        "E11 input report read call")

# E12: output write + CRC + ms->ticks helpers after pra_touch_input_read.
t = insert_after(t, [
"\terror = pra_touch_txn(reg, 2, buf, size);",
"\tif (!error) {",
"\t\t*lenp = (unsigned)size;",
"\t}",
"\treturn error;",
"}",
], [
"",
"/*",
" * 0177 rung A: one output-register write, [reg lo][reg hi] + payload with",
" * STOP on the last byte (the cyttsp5_write wire form, WORKLOG sec 3).",
" * Only the reset path calls this, behind pratouchreset=1.",
" */",
"static int",
"pra_touch_output_write(const uint8_t *frame, unsigned len)",
"{",
"\tuint8_t out[2u + PRA_TOUCH_BL_LEN];",
"",
"\tif (len != PRA_TOUCH_BL_LEN) {",
"\t\treturn EINVAL;",
"\t}",
"\tout[0] = (uint8_t)(PRA_TOUCH_OUT_REG & 0xffu);",
"\tout[1] = (uint8_t)(PRA_TOUCH_OUT_REG >> 8);",
"\tmemcpy(&out[2], frame, len);",
"\treturn pra_touch_txn(out, (unsigned)sizeof(out), NULL, 0);",
"}",
"",
"/*",
" * CRC-ITU-T V.41: poly 0x1021 MSB-first, no reflection, no final xor -",
" * the Linux crc_itu_t() algorithm (include/linux/crc-itu-t.h table form,",
" * bit-expanded; both agree on the launch frame). This is what mainline",
" * cyttsp5.c:621 computes over the four bytes after SOP.",
" */",
"static uint16_t",
"pra_touch_crc_itu(uint16_t crc, const uint8_t *p, unsigned len)",
"{",
"\tunsigned i, b;",
"",
"\tfor (i = 0; i < len; i++) {",
"\t\tcrc = (uint16_t)(crc ^ ((uint16_t)p[i] << 8));",
"\t\tfor (b = 0; b < 8; b++) {",
"\t\t\tcrc = (crc & 0x8000u) ?",
"\t\t\t    (uint16_t)((crc << 1) ^ 0x1021u) :",
"\t\t\t    (uint16_t)(crc << 1);",
"\t\t}",
"\t}",
"\treturn crc;",
"}",
"",
"/* ms -> whole ticks, at least 1 (bounded sleeps only, no busy spin). */",
"static unsigned",
"pra_touch_ms_ticks(unsigned ms)",
"{",
"\tunsigned t = (ms * (unsigned)hz + 999u) / 1000u;",
"",
"\treturn t < 1u ? 1u : t;",
"}",
], "E12 output write + crc + ms ticks")

# E15a: parse fills the per-report contact set (K3 per-slot release).
t = sub(t, [
"/*",
" * Parse one touch report (buffer as returned by pra_touch_input_read).",
" * Returns the contact count (0 for a valid release frame), or 0 with",
" * corrupt set when a field is impossible. Buttons (report id 0x3) are",
" * dropped silently (no button node on prague, live/dmesg.txt:4817).",
" * Layout per the header comment: count = 5 bits at bit 16 from buffer+3",
" * (bits [4:0] of byte [5]), records at [7 + 10*i].",
" */",
"static unsigned",
"pra_touch_parse(const uint8_t *buf, unsigned len, bool *corrupt,",
"    unsigned *slot, unsigned *x, unsigned *y, unsigned *p)",
"{",
], [
"/*",
" * Parse one touch report (buffer as returned by pra_touch_input_read).",
" * Returns the contact count (0 for a valid release frame), or 0 with",
" * corrupt set when a field is impossible. Buttons (report id 0x3) are",
" * dropped silently (no button node on prague, live/dmesg.txt:4817).",
" * Layout per the header comment: count = 5 bits at bit 16 from buffer+3",
" * (bits [4:0] of byte [5]), records at [7 + 10*i]. Every valid record",
" * also marks now[id] and records its coordinates (0177: the worker",
" * reconciles the per-slot down[] table against this contact set); the",
" * last record still fills slot/x/y/p for the stats line.",
" */",
"static unsigned",
"pra_touch_parse(const uint8_t *buf, unsigned len, bool *corrupt,",
"    bool *now, unsigned *nx, unsigned *ny,",
"    unsigned *slot, unsigned *x, unsigned *y, unsigned *p)",
"{",
], "E15a parse signature")

# E15b: parse stores each valid record into the contact set.
t = sub(t, [
"\t\t*slot = id;",
"\t\t*x = rx;",
"\t\t*y = ry;",
"\t\t*p = rp;",
"\t\tn = i + 1;",
], [
"\t\t*slot = id;",
"\t\t*x = rx;",
"\t\t*y = ry;",
"\t\t*p = rp;",
"\t\tnow[id] = true;",
"\t\tnx[id] = rx;",
"\t\tny[id] = ry;",
"\t\tn = i + 1;",
], "E15b parse contact set")

# E15c: worker-local contact-set arrays.
t = sub(t, [
"\t\t\tuint8_t buf[PRA_TOUCH_MAX_REPORT];",
"\t\t\tunsigned len = 0, slot = 0, x = 0, y = 0, p = 0;",
"\t\t\tbool corrupt;",
], [
"\t\t\tuint8_t buf[PRA_TOUCH_MAX_REPORT];",
"\t\t\tunsigned len = 0, slot = 0, x = 0, y = 0, p = 0;",
"\t\t\tbool now[MAX_CONTACTS] = { false };",
"\t\t\tunsigned nx[MAX_CONTACTS] = { 0 };",
"\t\t\tunsigned ny[MAX_CONTACTS] = { 0 };",
"\t\t\tbool corrupt;",
], "E15c worker contact arrays")

# E15d: parse call passes the contact set.
t = sub(t, [
"\t\t\t\tunsigned n = pra_touch_parse(buf, len,",
"\t\t\t\t    &corrupt, &slot, &x, &y, &p);",
], [
"\t\t\t\tunsigned n = pra_touch_parse(buf, len,",
"\t\t\t\t    &corrupt, now, nx, ny, &slot, &x, &y, &p);",
], "E15d parse call")

# E13: injection helpers after pra_touch_parse (tail after the E15b edit).
t = insert_after(t, [
"\t\t*slot = id;",
"\t\t*x = rx;",
"\t\t*y = ry;",
"\t\t*p = rp;",
"\t\tnow[id] = true;",
"\t\tnx[id] = rx;",
"\t\tny[id] = ry;",
"\t\tn = i + 1;",
"\t}",
"\treturn n;",
"}",
], [
"",
"/*",
" * 0177 rung B: report one TT5 contact into the live SweetHIDTouch",
" * IOHIDEventService (SweetHID.cpp:565-571 sweet_hid_touch; it re-checks",
" * the finger bound at :468). The first injection prints one line - the",
" * CI marker and the boot-time proof the call site is live (per-event",
" * lines are SweetHID.cpp:543-546's own \"SWEET HID: touch ...\"). Worker",
" * thread only, like the counters above.",
" */",
"static void",
"pra_touch_inject(unsigned slot, bool down, int x, int y)",
"{",
"\tstatic bool printed_once;",
"",
"\tif (down) {",
"\t\tpra_down[slot] = true;",
"\t\tpra_last_x[slot] = x;",
"\t\tpra_last_y[slot] = y;",
"\t} else {",
"\t\tpra_down[slot] = false;",
"\t}",
"\tif (!printed_once) {",
"\t\tprinted_once = true;",
"\t\tprintf(\"PRA touch: hid inject slot=%u %s x=%d y=%d\\n\", slot,",
"\t\t    down ? \"down\" : \"up\", x, y);",
"\t}",
"\tsweet_hid_touch((int)slot, down ? 1 : 0, x, y);",
"}",
"",
"/* Donor a5xelte_touch.c:484-494 pattern: everything still down goes up",
" * with its last-known coordinates. Runs after a worker error - per-slot",
" * lifts are handled by pra_touch_reconcile below. */",
"static void",
"pra_touch_release_all(void)",
"{",
"\tfor (unsigned slot = 0; slot < MAX_CONTACTS; slot++) {",
"\t\tif (pra_down[slot]) {",
"\t\t\tpra_touch_inject(slot, false, pra_last_x[slot],",
"\t\t\t    pra_last_y[slot]);",
"\t\t}",
"\t}",
"}",
"",
"/*",
" * 0177 rung B, pra_live-gated (the worker only calls this from the",
" * do_read path, which requires pra_live && input_reg != 0): reconcile",
" * the down[] table against the report's contact set. Present slots are",
" * pressed/moved; every still-down slot missing from the report goes up",
" * with its last-known coordinates (donor a5xelte_touch.c:527/529), so",
" * a 2-finger report followed by a 1-finger report releases the lifted",
" * finger instead of leaving a ghost touch.",
" */",
"static void",
"pra_touch_reconcile(const bool *now, const unsigned *nx,",
"    const unsigned *ny)",
"{",
"\tfor (unsigned s = 0; s < MAX_CONTACTS; s++) {",
"\t\tif (now[s]) {",
"\t\t\tpra_touch_inject(s, true, (int)nx[s], (int)ny[s]);",
"\t\t} else if (pra_down[s]) {",
"\t\t\tpra_touch_inject(s, false, pra_last_x[s],",
"\t\t\t    pra_last_y[s]);",
"\t\t}",
"\t}",
"}",
], "E13 inject + release_all + reconcile")

# E14: worker error branch releases all slots.
t = sub(t, [
"\t\t\tif (error) {",
"\t\t\t\terr_total++;",
"\t\t\t\tbackoff = (unsigned)loops_per_1s;",
"\t\t\t} else if (len) {",
], [
"\t\t\tif (error) {",
"\t\t\t\terr_total++;",
"\t\t\t\t/* Donor error recovery: a failed read must",
"\t\t\t\t * not leave contacts stuck down (donor",
"\t\t\t\t * a5xelte_touch.c:484-494). */",
"\t\t\t\tpra_touch_release_all();",
"\t\t\t\tbackoff = (unsigned)loops_per_1s;",
"\t\t\t} else if (len) {",
], "E14 worker error release-all")

# E15: the contact block becomes the per-slot reconcile loop (K3).
t = sub(t, [
"\t\t\t\t} else {",
"\t\t\t\t\tevt_total++;",
"\t\t\t\t\tif (n) {",
"\t\t\t\t\t\t/* last record wins */",
"\t\t\t\t\t\tlast_contact_slot = (int)slot;",
"\t\t\t\t\t\tlast_contact_x = (int)x;",
"\t\t\t\t\t\tlast_contact_y = (int)y;",
"\t\t\t\t\t\tlast_contact_p = (int)p;",
"\t\t\t\t\t\thave_contact = true;",
"\t\t\t\t\t} else {",
"\t\t\t\t\t\t/* zero contacts = release */",
"\t\t\t\t\t\thave_contact = false;",
"\t\t\t\t\t}",
"\t\t\t\t}",
], [
"\t\t\t\t} else {",
"\t\t\t\t\tevt_total++;",
"\t\t\t\t\t/*",
"\t\t\t\t\t * 0177 rung B, pra_live-gated (do_read",
"\t\t\t\t\t * above is true only when pra_live &&",
"\t\t\t\t\t * input_reg != 0, so nothing here runs",
"\t\t\t\t\t * with a dead IC). Reconcile the down[]",
"\t\t\t\t\t * table against this report's contact",
"\t\t\t\t\t * set (K3): press/move for present",
"\t\t\t\t\t * slots, release for lifted ones - a",
"\t\t\t\t\t * 2-finger report then a 1-finger",
"\t\t\t\t\t * report must not leave a ghost.",
"\t\t\t\t\t */",
"\t\t\t\t\tpra_touch_reconcile(now, nx, ny);",
"\t\t\t\t\t/* 0172 store kept: the 10 s",
"\t\t\t\t\t * stats line stays the first-",
"\t\t\t\t\t * test signal (last record",
"\t\t\t\t\t * wins, as before). */",
"\t\t\t\t\tif (n) {",
"\t\t\t\t\t\tlast_contact_slot = (int)slot;",
"\t\t\t\t\t\tlast_contact_x = (int)x;",
"\t\t\t\t\t\tlast_contact_y = (int)y;",
"\t\t\t\t\t\tlast_contact_p = (int)p;",
"\t\t\t\t\t\thave_contact = true;",
"\t\t\t\t\t} else {",
"\t\t\t\t\t\thave_contact = false;",
"\t\t\t\t\t}",
"\t\t\t\t}",
], "E15 worker per-slot reconcile")

# E16: the reset+launch function before pra_touch_probe.
t = insert_before(t, [
"/* One-shot entry point, called from the IOFindBSDRoot PRA block",
" * (iokit/bsddev/IOKitBSDInit.cpp) only when the cmdline has pratouch=1. */",
"void",
"pra_touch_probe(void)",
], [
"/*",
" * 0177 rung A (pratouchreset=1, OFF by default): readback-verified XRES",
" * toggle of gpio18.1, then the BL_LAUNCH_APP frame to output register",
" * 0x0004, then a bounded wait; the descriptor re-read in pra_touch_probe",
" * (step 4) reports the outcome. Order per mainline cyttsp5_startup",
" * (cyttsp5.c:775-799): reset, launch app, read descriptor - \"the device",
" * starts in bootloader mode because of a power-on-reset\" (:785-788).",
" * Every stage has a fixed tick budget (~230 ms nominal for the whole",
" * sequence; tsleep, so no hard upper bound); any failure increments",
" * pra_rst_fail, prints once and leaves the probe exactly where",
" * 0172/0175 would be.",
" */",
"static void",
"pra_touch_reset_launch(void)",
"{",
"\tvm_offset_t rst;",
"\tuint32_t dir, v;",
"\tuint8_t bl[PRA_TOUCH_BL_LEN];",
"\tuint16_t crc;",
"\tint error;",
"",
"\t/* 1. gpio18.1: set the DIR bit (pl061 pin direction, 1 = output)",
"\t * and toggle DAT, both readback-verified. Polarity per mainline",
"\t * cyttsp5.c (asserted HIGH :873-874, deassert :883); the stock",
"\t * vendor toggle details are UNKNOWN (WORKLOG sec 9) - readback",
"\t * failures abort the rung instead of guessing. */",
"\trst = ml_io_map((vm_offset_t)PRA_TOUCH_RST_BASE,",
"\t    (vm_offset_t)PRA_TOUCH_RST_SIZE);",
"\tif (!rst) {",
"\t\tpra_rst_fail++;",
"\t\tprintf(\"PRA touch: reset gpio18.1 map failed, probe \"",
"\t\t    \"continues\\n\");",
"\t\treturn;",
"\t}",
"\tdir = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);",
"\tpra_touch_wr32(rst, PRA_TOUCH_RST_DIR_OFF, dir | PRA_TOUCH_RST_DIR_BIT);",
"\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DIR_OFF);",
"\tif ((v & PRA_TOUCH_RST_DIR_BIT) == 0) {",
"\t\tpra_rst_fail++;",
"\t\tprintf(\"PRA touch: reset gpio18.1 dir readback failed dir=%x\\n\",",
"\t\t    v);",
"\t\treturn;",
"\t}",
"\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF, PRA_TOUCH_RST_DAT_BIT);",
"\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
"\tif ((v & PRA_TOUCH_RST_DAT_BIT) == 0) {",
"\t\tpra_rst_fail++;",
"\t\tprintf(\"PRA touch: reset gpio18.1 assert readback failed \"",
"\t\t    \"dat=%x\\n\", v);",
"\t\treturn;",
"\t}",
"\t/* Reset pulse: mainline needs >= 10 us (cyttsp5.c:881); a 10 ms",
"\t * tsleep is far above that. */",
"\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
"\t    pra_touch_ms_ticks(10u));",
"\tpra_touch_wr32(rst, PRA_TOUCH_RST_DAT_OFF, 0);",
"\tv = pra_touch_rd32(rst, PRA_TOUCH_RST_DAT_OFF);",
"\tif ((v & PRA_TOUCH_RST_DAT_BIT) != 0) {",
"\t\tpra_rst_fail++;",
"\t\tprintf(\"PRA touch: reset gpio18.1 deassert readback failed \"",
"\t\t    \"dat=%x\\n\", v);",
"\t\treturn;",
"\t}",
"\t/* Device-up delay: 20 ms (mainline cyttsp5.c:885-886). */",
"\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
"\t    pra_touch_ms_ticks(20u));",
"\tprintf(\"PRA touch: reset gpio18.1 done dir=%x dat=%x\\n\", dir, v);",
"",
"\t/* 2. BL_LAUNCH_APP, byte-for-byte mainline cyttsp5.c:615-623. */",
"\tbl[0] = 0x0Bu;                  /* u16 11 = whole frame length */",
"\tbl[1] = 0x00u;",
"\tbl[2] = 0x40u;                  /* HID_BL_OUTPUT_REPORT_ID (:70) */",
"\tbl[3] = 0x00u;                  /* reserved (:617) */",
"\tbl[4] = 0x01u;                  /* SOP (:34) */",
"\tbl[5] = 0x3Bu;                  /* LAUNCH_APP (:36) */",
"\tbl[6] = 0x00u;                  /* u16 0x0000 (:620) */",
"\tbl[7] = 0x00u;",
"\tcrc = pra_touch_crc_itu(0xFFFFu, &bl[4], 4);",
"\tbl[8] = (uint8_t)(crc & 0xffu);         /* LE16 (:622) */",
"\tbl[9] = (uint8_t)(crc >> 8);",
"\tbl[10] = 0x17u;                 /* EOP (:35) */",
"\terror = pra_touch_output_write(bl, PRA_TOUCH_BL_LEN);",
"\tif (error) {",
"\t\tpra_rst_fail++;",
"\t\tprintf(\"PRA touch: BL_LAUNCH_APP write failed err=%d, probe \"",
"\t\t    \"continues\\n\", error);",
"\t\treturn;",
"\t}",
"\tprintf(\"PRA touch: BL_LAUNCH_APP sent crc=%#x\\n\", crc);",
"",
"\t/* 3. App-up budget: mainline waits up to 200 ms for the launch",
"\t * response (CY_HID_OUTPUT_TIMEOUT_MS, cyttsp5.c:87,632-638); with",
"\t * no IRQ path the same budget is a ~200 ms tsleep (no hard upper",
"\t * bound). The descriptor re-read in step 4 decides pra_live either",
"\t * way. */",
"\t(void)tsleep(&pra_touch_chan, PZERO, \"pratrst\",",
"\t    pra_touch_ms_ticks(200u));",
"}",
"",
], "E16 reset_launch function")

# E17: parse the boot-arg.
t = sub(t, [
"\tbool want = false;",
"\tuint32_t dbg = 0;",
], [
"\tbool want = false;",
"\tuint32_t dbg = 0;",
"\tuint32_t rst = 0;",
], "E17 rst decl")
t = sub(t, [
"\t(void)PE_parse_boot_argn(\"pratouchdbg\", &dbg, sizeof(dbg));",
"\tpra_touch_dbg = dbg == 1;",
], [
"\t(void)PE_parse_boot_argn(\"pratouchdbg\", &dbg, sizeof(dbg));",
"\tpra_touch_dbg = dbg == 1;",
"\t(void)PE_parse_boot_argn(\"pratouchreset\", &rst, sizeof(rst));",
"\tpra_touch_rst = rst == 1;",
"\tif (pra_touch_rst) {",
"\t\t/*",
"\t\t * Rung A on: transactions go through pra_touch_txn, which",
"\t\t * takes the shared bus mutex and configures the controller",
"\t\t * before the first transaction (the descriptor re-read in",
"\t\t * step 4 then decides pra_live).",
"\t\t */",
"\t\tpra_touch_bus_on = true;",
"\t}",
], "E17 pratouchreset parse")

# E18: step 3.5 between the IRQ line and the descriptor read.
t = insert_after(t, [
"\tprintf(\"PRA touch: irq gpio28.0 dat=%x dir=%x idle=%d\\n\", dat, dir,",
"\t    idle_level);",
], [
"",
"\t/*",
"\t * 3.5 (0177, pratouchreset=1 only): readback-verified XRES toggle +",
"\t * BL_LAUNCH_APP attempt (rung A). Without the boot-arg this is",
"\t * skipped and step 4 below behaves exactly as in 0172/0175.",
"\t */",
"\tif (pra_touch_rst) {",
"\t\tpra_touch_reset_launch();",
"\t}",
], "E18 step 3.5")

print(f"[1] pra_touch.c: {n0} -> {len(t)} lines, all anchors unique")
touch_new = t

# ======================================================================
# 2. bsd/dev/pra_charger.c  (base = buildtree, post-0176)
# ======================================================================
charger_old = read_lines(f"{BT}/bsd/dev/pra_charger.c")
c = list(charger_old)
n0 = len(c)

# C1: externs + owner id after the other externs.
c = insert_after(c, [
"extern void thread_deallocate(thread_t);",
"extern int hz;",
], [
"",
"/*",
" * 0177: shared i2c2 arbitration with pra_touch.c (WORKLOG sec 3 hazard,",
" * sec 10.4). The mutex and owner tag live in pra_touch.c; take() returns",
" * true when someone else configured the controller since we last did, and",
" * every transaction entry point below re-runs its setup in that case, so",
" * no transaction can run against a foreign TAR. pra_bus_owner starts at",
" * PRA_BUS_CHARGER, and without pratouchreset=1 the touch side never takes",
" * the mutex, so this driver's transaction sequence is unchanged.",
" */",
"#define PRA_BUS_CHARGER 2       /* owner id, must match pra_touch.c */",
"",
"extern bool pra_i2c_bus_take(int who);",
"extern void pra_i2c_bus_drop(void);",
], "C1 externs")

# C2: split pra_i2c_setup into the nolock body + a locked wrapper.
c = sub(c, [
"/* Take the controller from whatever the bootloader left to a known",
" * standard-mode master pointed at addr. This is controller state, not",
" * chip state: the charger register contents are untouched. */",
"static int",
"pra_i2c_setup(struct pra_i2c_host *h, uint8_t addr)",
"{",
], [
"/* Take the controller from whatever the bootloader left to a known",
" * standard-mode master pointed at addr. This is controller state, not",
" * chip state: the charger register contents are untouched. Callers hold",
" * the shared bus mutex (pra_i2c_setup) or run inside a transaction that",
" * already took it (pra_i2c_read_reg/pra_i2c_write_reg). */",
"static int",
"pra_i2c_setup_nolock(struct pra_i2c_host *h, uint8_t addr)",
"{",
], "C2 setup rename")

c = insert_after(c, [
"\tpra_i2c_wr32(r, DW_IC_ENABLE, 1);",
"\tif (pra_i2c_wait_enable(r, true)) {",
"\t\treturn ETIMEDOUT;",
"\t}",
"\treturn 0;",
"}",
], [
"",
"/* 0177: locked wrapper - the one probe-time caller (pra_probe_chip). */",
"static int",
"pra_i2c_setup(struct pra_i2c_host *h, uint8_t addr)",
"{",
"\tint error;",
"",
"\t(void)pra_i2c_bus_take(PRA_BUS_CHARGER);",
"\terror = pra_i2c_setup_nolock(h, addr);",
"\tpra_i2c_bus_drop();",
"\treturn error;",
"}",
], "C2 setup wrapper")

# C3: pra_i2c_read_reg through the bus mutex.
c = sub(c, [
"static int",
"pra_i2c_read_reg(struct pra_i2c_host *h, uint8_t reg, uint8_t *val)",
"{",
"\tvm_offset_t r = h->regs;",
"\tuint32_t raw;",
"\tint error = ETIMEDOUT;",
"",
"\tif (h->addr == 0) {",
"\t\treturn ENXIO;",
"\t}",
"\tpra_i2c_wait_idle(r);",
], [
"static int",
"pra_i2c_read_reg(struct pra_i2c_host *h, uint8_t reg, uint8_t *val)",
"{",
"\tvm_offset_t r = h->regs;",
"\tuint32_t raw;",
"\tbool reowned;",
"\tint error = ETIMEDOUT;",
"",
"\tif (h->addr == 0) {",
"\t\treturn ENXIO;",
"\t}",
"\t/* 0177: one transaction at a time on the shared controller. If the",
"\t * touch driver (or boot state) reconfigured it since we last did,",
"\t * re-setup first so the read cannot run against a foreign TAR. */",
"\treowned = pra_i2c_bus_take(PRA_BUS_CHARGER);",
"\tif (reowned && pra_i2c_setup_nolock(h, h->addr)) {",
"\t\th->addr = 0;            /* same sentinel as the timeout below */",
"\t\tpra_i2c_bus_drop();",
"\t\treturn ETIMEDOUT;",
"\t}",
"\tpra_i2c_wait_idle(r);",
], "C3 read_reg take")

c = sub(c, [
"\tif (error == ETIMEDOUT) {",
"\t\t/* Force reconfiguration before the next attempt. */",
"\t\th->addr = 0;",
"\t}",
"\treturn error;",
"}",
], [
"\tif (error == ETIMEDOUT) {",
"\t\t/* Force reconfiguration before the next attempt. */",
"\t\th->addr = 0;",
"\t}",
"\tpra_i2c_bus_drop();",
"\treturn error;",
"}",
], "C3 read_reg drop")

# C4: pra_i2c_write_reg through the bus mutex.
c = sub(c, [
"static int",
"pra_i2c_write_reg(struct pra_i2c_host *h, uint8_t reg, uint8_t val)",
"{",
"\tvm_offset_t r = h->regs;",
"\tuint32_t raw;",
"\tint error = ETIMEDOUT;",
"",
"\tif (h->addr == 0) {",
"\t\treturn ENXIO;",
"\t}",
"\tpra_i2c_wait_idle(r);",
], [
"static int",
"pra_i2c_write_reg(struct pra_i2c_host *h, uint8_t reg, uint8_t val)",
"{",
"\tvm_offset_t r = h->regs;",
"\tuint32_t raw;",
"\tbool reowned;",
"\tint error = ETIMEDOUT;",
"",
"\tif (h->addr == 0) {",
"\t\treturn ENXIO;",
"\t}",
"\t/* 0177: same arbitration as pra_i2c_read_reg above. */",
"\treowned = pra_i2c_bus_take(PRA_BUS_CHARGER);",
"\tif (reowned && pra_i2c_setup_nolock(h, h->addr)) {",
"\t\th->addr = 0;",
"\t\tpra_i2c_bus_drop();",
"\t\treturn ETIMEDOUT;",
"\t}",
"\tpra_i2c_wait_idle(r);",
], "C4 write_reg take")

c = sub(c, [
"\tif (error == ETIMEDOUT) {",
"\t\th->addr = 0;",
"\t}",
"\treturn error;",
"}",
], [
"\tif (error == ETIMEDOUT) {",
"\t\th->addr = 0;",
"\t}",
"\tpra_i2c_bus_drop();",
"\treturn error;",
"}",
], "C4 write_reg drop")

print(f"[2] pra_charger.c: {n0} -> {len(c)} lines, all anchors unique")
charger_new = c

# ======================================================================
# 3. Marker sanity + the CI asserts.
# Per HEAD f851352 (run 44141348138): a yml hunk inside a patch CANNOT
# apply in CI's dxb tree and would silently skip the whole patch - so this
# patch is xnu-tree-only and the marker asserts go into the repo's
# .github/workflows/xnu.yml as a direct working-tree edit for the
# orchestrator to commit next to the patch (same as the 0176 asserts).
# ======================================================================
for marker in ("PRA touch: hid inject", "PRA touch: BL_LAUNCH_APP",
               "PRA touch: reset gpio18.1"):
    assert any(marker in l for l in touch_new), f"marker missing: {marker}"
print("[3] markers present in expected pra_touch.c")

yml_path = f"{REPO}/.github/workflows/xnu.yml"
y = read_lines(yml_path)
if any("'PRA touch: hid inject'" in l for l in y):
    print("[3] yml already carries the 0177 asserts, skipping insert")
else:
    anchor = "          strings -a \"$kernel\" | grep -F 'cal=%llu.%06llu' >/dev/null"
    assert sum(1 for l in y if l == anchor) == 1, "yml assert anchor not unique"
    block = [
    "          # 0177 touch guard: rung A (readback-verified XRES toggle + the",
    "          # BL_LAUNCH_APP frame, all behind pratouchreset=1 - OFF by",
    "          # default, the driver stays inert without it) and rung B (valid",
    "          # TT5 contacts injected into SweetHIDTouch via sweet_hid_touch,",
    "          # gated on pra_live). Both format strings are compiled in",
    "          # regardless of the boot-arg, so a silently skipped patch fails",
    "          # here instead of shipping (0155 lesson). Workflow changes are",
    "          # direct commits (see the 0176 note above).",
    "          strings -a \"$kernel\" | grep -F 'PRA touch: hid inject' >/dev/null",
    "          strings -a \"$kernel\" | grep -F 'PRA touch: BL_LAUNCH_APP' >/dev/null",
    ]
    i = next(i for i, l in enumerate(y) if l == anchor)
    y = y[:i + 1] + block + y[i + 1:]
    with open(yml_path, "w", encoding="utf-8") as f:
        f.write("\n".join(y) + "\n")
y_new = y
check = read_lines(yml_path)
assert check == y_new, "yml write-back mismatch"
assert any("'PRA touch: hid inject'" in l for l in check)
assert any("'PRA touch: BL_LAUNCH_APP'" in l for l in check)
print(f"[3] .github/workflows/xnu.yml: 0177 asserts present (direct"
      f" working-tree edit, {len(check)} lines)")

# ======================================================================
# 4. Emit the patch (gen0175.py format: header + unified diffs, lineterm="")
# ======================================================================
d1 = difflib.unified_diff(touch_old, touch_new,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")
d2 = difflib.unified_diff(charger_old, charger_new,
                          fromfile="a/bsd/dev/pra_charger.c",
                          tofile="b/bsd/dev/pra_charger.c", n=3, lineterm="")
header = """pra: 0177 - touch driver: BL reset+launch attempt, per-slot HID injection, shared i2c2 arbitration

Rung A (pratouchreset=1, OFF by default; WORKLOG sec 10.3): the descriptor
NACK's root cause is UNKNOWN (touch rail state / deep-sleep inheritance rank
first, per the design note sec 2). Behind the boot-arg the probe attempts the
standard recovery: a readback-verified XRES toggle of gpio18.1 (gpio145, bank
@0xE8A1D000), the 11-byte BL_LAUNCH_APP frame to output register 0x0004
(mainline cyttsp5.c:609-626, CRC-ITU-T init 0xFFFF over bytes [4..7]), a
~200 ms sleep, and the existing descriptor re-read reports the outcome. Every
stage has a fixed tick budget (~230 ms nominal for the whole sequence; tsleep,
so no hard upper bound); any failure is counted (pra_rst_fail) and the probe
continues as without the boot-arg.

Rung B: TT5 touch reports are injected into the live SweetHIDTouch
IOHIDEventService via sweet_hid_touch() (SweetHID.cpp:565-571; donor
a5xelte_touch.c:527/529 pattern) with real per-slot down[] tracking: present
slots are pressed/moved, and any still-down slot missing from the report is
released with its last-known coordinates (a 2-finger report followed by a
1-finger report releases the lifted finger - no ghost touch). Worker errors
release ALL slots. Gated on pra_live (do_read requires pra_live &&
input_reg != 0): with a dead IC the driver is inert. The 10 s stats print is
kept unchanged (first-test signal + CI marker).

Shared i2c2 arbitration with pra_charger.c (WORKLOG sec 3 hazard + sec 10.4,
mandatory before event plumbing): one bus mutex + owner tag; a taker that
finds a foreign owner reconfigures the controller before transacting. The
charger is the boot default owner. The mutex is held only across bounded MMIO
spin loops - no tsleep/delay under the lock in either driver (worst-case hold
~40 ms on a dead bus, microseconds on a live one).

Functionally neutral without pratouchreset=1: the probe runs exactly as today
(no reset, no injection, no controller or gpio writes); the charger's read/
write transactions now hold the shared mutex (added locking, same sequence
and same bytes on the wire).

This patch is xnu-tree-only (the 0176 lesson, run 44141348138): the marker
asserts 'PRA touch: hid inject' and 'PRA touch: BL_LAUNCH_APP' go into
.github/workflows/xnu.yml as a direct commit beside this patch, never as a
yml hunk inside a patch (that cannot apply in the dxb tree and silently
skips the whole patch).
"""
with open(OUT, "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write(header + "\n".join(list(d1) + list(d2)) + "\n")
print(f"[4] wrote {OUT}")

# ======================================================================
# 5. Verify three ways in scratch repos seeded with the true bases
# ======================================================================
BASES = (("bsd/dev/pra_touch.c", "\n".join(touch_old) + "\n"),
         ("bsd/dev/pra_charger.c", "\n".join(charger_old) + "\n"))
EXPECT = (("bsd/dev/pra_touch.c", "\n".join(touch_new) + "\n"),
          ("bsd/dev/pra_charger.c", "\n".join(charger_new) + "\n"))


def seed(root):
    for path, content in BASES:
        fp = os.path.join(root, path)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w").write(content)
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(["git", "-C", root, "config", "user.email", "v@v"], check=True)
    subprocess.run(["git", "-C", root, "config", "user.name", "v"], check=True)
    subprocess.run(["git", "-C", root, "add", "-A"], check=True)
    subprocess.run(["git", "-C", root, "commit", "-qm", "base"], check=True)


scratch = tempfile.mkdtemp(prefix="v0177")
seed(scratch)
r0 = subprocess.run(["git", "-C", scratch, "apply", "--check", "-v", OUT],
                    capture_output=True, text=True)
out0 = r0.stdout + r0.stderr
print(f"[5] way 1: git apply --check rc={r0.returncode}")
for l in out0.splitlines():
    if any(k in l for k in ("Skipped", "error", "Checking")):
        print(f"    {l}")
assert r0.returncode == 0 and "Skipped" not in out0

r2 = subprocess.run(["patch", "-p1", "--fuzz=0", "--dry-run", "-i", OUT],
                    cwd=scratch, capture_output=True, text=True)
print(f"[5] way 2: GNU patch --fuzz=0 --dry-run rc={r2.returncode}")
if r2.returncode != 0:
    print(r2.stdout + r2.stderr)
assert r2.returncode == 0

scratch2 = tempfile.mkdtemp(prefix="v0177b")
seed(scratch2)
r = subprocess.run(["git", "-C", scratch2, "apply", "-v", OUT],
                   capture_output=True, text=True)
outr = r.stdout + r.stderr
print(f"[5] way 3: git apply rc={r.returncode}")
for l in outr.splitlines():
    if "Skipped" in l or "error" in l:
        print(f"    {l}")
assert r.returncode == 0 and "Skipped" not in outr
for path, expect in EXPECT:
    got = open(os.path.join(scratch2, path)).read()
    assert got == expect, f"{path} mismatch"
    print(f"[5] way 3: {path} applied == expected (byte-identical)")
shutil.rmtree(scratch)
shutil.rmtree(scratch2)
print("[6] VERIFY PASS: 0177 applies to the replayed bases, three ways")

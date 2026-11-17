# CLAIM: 0177 (touch HID injection + I2C arbitration, behind pratouchreset=1)

author: GLM-5.3-Flash subagent (ZCode session 2026-11-17, 11.5M tokens,
94 tool uses, 58 min; generator work/gen0177.py from the CI-compiled bases
of run 44119547672; three-way verify PASS + gcc -Wall -Wextra stub-header
syntax check rc=0 on both patched files + CRC/injection logic unit tests).
Design context: work/touch-design-note-2026-11-17.md (evidence 2), the lock
audit (evidence 3).

K1: BEHAVIOR-NEUTRAL WITHOUT `pratouchreset=1` — byte-identical to 0175:
    the touch side never takes the bus mutex, never calls controller setup,
    never writes the controller or the gpio18 bank; pra_touch_txn passes
    through to the 0172 sentinel path (ENXIO); pra_live stays false so
    injection is inert; the 10 s stats print is untouched; the charger
    sequence is unchanged (the bus owner tag starts as charger).
K2: rung A (behind the boot-arg): readback-verified XRES toggle on gpio18.1
    (bank 0xE8A1D000, DAT base+0x4, gpio145) + the 11-byte BL_LAUNCH_APP
    frame `0B 00 40 00 01 3B 00 00 CRC CRC 17` (CRC-ITU-T init 0xFFFF over
    bytes [4..7]), bounded <=300 ms, then descriptor re-read.
K3: rung B: `sweet_hid_touch(slot, down, x, y)` injection at the 0172
    contact-handling site, 10-slot down[] table, release-ALL on worker
    error, gated on pra_live; the 10 s stats print kept (first-test signal).
K4: shared I2C arbitration: one mutex + owner tag (pra_i2c_bus_take(who)/
    drop, defined in pra_touch.c, charger is the boot default owner); a
    taker finding a foreign owner re-runs its own setup before transacting;
    no lock nesting (charger_lock -> bus only), no deadlock cycles. Wired:
    charger at pra_i2c_read_reg/pra_i2c_write_reg (locked setup wrapper),
    touch through one pra_touch_txn choke point.
K5: KEY FINDING: 0172's pra_i2c_setup was dead code (pra_tar stayed 0) —
    the rings' "HID desc read failed err=6 (address NACK)" is the
    not-configured-controller sentinel, NOT proof of a dead IC. 0177
    configures the controller only behind the boot-arg.
K6: CI markers `PRA touch: hid inject` + `PRA touch: BL_LAUNCH_APP` are
    asserted via a DIRECT edit to .github/workflows/xnu.yml (+10 lines,
    working tree, to be committed beside the patch) — NOT inside the patch
    (the yml-hunk silent-skip lesson, run 44141348138). The patch itself is
    xnu-tree-only (pra_touch.c + pra_charger.c).
K7: first-test cmdline (WORKLOG sec 12.7): append ` pratouchreset=1` after
    `pratouch=1` via the CMDLINE env; packaging keeps the 11 critical args;
    flashing the result REQUIRES PRA_ALLOW_ANY_CMDLINE=1 (the extra arg is
    not in the 11-arg gate). Pass signal: `HID desc len=32 bcd=0x100` /
    "app mode confirmed", then `reports=N ... last: slot=0 x=... y=...`,
    then the one-shot `hid inject` line and SweetHID's `touch N down`.

Falsifiers: any non-pratouchreset behavioral delta vs 0175 (K1 broken); a
deadlock or unbalanced take/drop in the arbitration (K4); injection firing
while pra_live is false (K3); an apply failure of the patch against the
CI-compiled bases.

## ADDENDUM — review round 1 (work/pkt-192253: 2 refuted / 5 weak / 0
## survive); outcomes adopted

- K1 REVISED (valid): "byte-identical to 0175" was false — the charger's
  read/write transactions now hold the shared bus mutex (added locking,
  same sequence and bytes on the wire). The claim is FUNCTIONAL neutrality:
  without the boot-arg the driver stays inert, the charger sequence is
  unchanged, no re-setup churn.
- K5 ACCEPTED-REFUTED (valid): the "dead setup" finding contradicted the
  design note's own ring text (COMP_VERSION=3132302a read successfully
  before the descriptor NACK — impossible if every transaction ENXIO'd).
  Dropped from header and code; the NACK cause returns to UNKNOWN (rails/
  deep-sleep ranked first). Rung A remains a reset attempt, not a root-cause
  fix. (Subagent note for the record: COMP_VERSION is read via direct MMIO,
  not an I2C transaction, so the refutation has a hole — the diagnosis is
  still gone from all claims.)
- K3 FIXED (FAULT-class): per-slot reconcile added — pra_touch_parse fills a
  per-report contact set and pra_touch_reconcile presses/moves present slots
  and releases every still-down slot missing from the report (the 2-finger
  -> 1-finger ghost case), with last-known coords; release_all stays
  worker-error-only. Functional test with the real extracted code: the
  ghost case releases slot 0 at (100,200) while slot 2 moves. The pra_live
  gate is at the worker call site (do_read runs only when pra_live and the
  input reg are set).
- K4 VERIFIED: <kern/locks.h> is already included in both base files
  (pra_touch.c:89, pra_charger.c:40); the sleep audit found the only
  tsleeps outside take/drop (worker tick, charger poll, reset waits);
  pra_i2c_xfer/setup are bounded MMIO spin loops — no sleep-in-lock; the
  bus mutex's worst-case hold is ~40 ms on a dead bus (documented).
- K2 REVISED (valid): the reset-path delays are tsleep — "~230 ms nominal,
  no hard upper bound", not "bounded <=300 ms".
- K7 VERIFIED with line numbers: both tools/pra_package.sh (:95-98) and
  tools/pra_flash_skip.sh (:58-63) refuse only MISSING critical args;
  an appended cmdline keeping all 11 passes both. PRA_ALLOW_ANY_CMDLINE=1
  is NOT required for pratouchreset=1 (WORKLOG 12.7's "REQUIRED" is stale).
- K6: the yml asserts are a direct working-tree edit committed beside the
  patch (verified: +10 lines after 0176's asserts, same style).


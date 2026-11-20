# CLAIM: 0190 (the touch INPUT poll every worker tick)

author: Buffy (Freebuff session 2026-11-20; reviewed on
opencode/nemotron-3.5-super-vl-free per user direction). The patch is
emitted by work/gen0190.py from work/ci190/post0189 = work/ci189/pre0189
(the post-0188 reconstruction) + the 0189 patch applied; three-way
verify PASS + the structural assertions (evidence 4).

Base evidence: boot T13 (ring54, evidence 1) + the post-0189 worker
source (evidence 2) + the vendor read model (evidence 3) + the patch
and its verify (evidence 4-5).

The patch (evidence 5) makes these claims:

K1: THE T13 RESULT. The 0189 length poll worked on the FIRST attempt:
    `desc attempt 1: the response received (32 bytes, hdr=0x20),
    irq 0->0`; the parse accepted it (`HID desc len=32 bcd=0x100
    rid=0x2 in=0x3 out=0x4 cmd=0x5 data=0x6 vid=0x4b4 pid=0xc101
    ver=0x100`); `app mode confirmed, input reg 0x3 max_input=254`;
    the worker then read 42 real reports (41 new reports in the 50 s
    between the 57500 and 62500 ticks) and injected 9 SweetHID
    events - 5 downs, 4 ups (`SWEET HID: touch 0 down at 588,1878
    edge` ... `touch 0 up at 731,548`). The pad stayed LOW
    throughout the logged window (`irq lo/hi = 62500/0`, 62,500 x
    10 ms). So the IC, bus, mode and injection
    all function; the user still saw no touch.

K2: THE 1 Hz GATE (the defect). The worker's read gate was: read when
    the IRQ level differs from `idle_level` (sampled 0 at probe), OR
    at the 1 Hz heartbeat (`loops - last_heartbeat >= loops_per_1s`).
    The pad never differs from 0, so only the 1 Hz branch fired. T13
    measured it: 42 reports over ~50 s of touch = ~0.8 Hz. That is far
    below the rate any gesture recognizer needs; a swipe became one or
    two points a second.

K3: THE FIX. With `pra_live && input_reg != 0`, set `do_read = true`
    on EVERY tick (10 ms). The vendor is IRQ-driven; the pad is
    unusable, so the poll replaces the IRQ. The input read
    (`pra_touch_input_read`: 2-byte length word; 0 or 2 = nothing
    pending; then the payload) is unchanged, as is the 1 s error
    backoff (`backoff`, fed by `loops_per_1s`, which also sets the
    10 s stats cadence - it is NOT dead state), and the level
    histogram (`irq_hi`/`irq_lo`) still counts each sample for the
    ring (evidence 2). The dead `last_heartbeat` state is removed and the stale
    comment that described the level-diff/1 Hz design is replaced.

K4: WHY EVERY TICK IS SAFE. An idle tick is one 2-byte register
    write + 2-byte read (4 bus bytes); a tick with data pending is
    that plus the report (2 transactions). At 10 ms that is ~100
    transactions/s idle and up to ~200/s if every tick had data
    (~800 B/s of transaction overhead at 4 B each, plus the report
    payload) - the SAME ORDER as the 0189 descriptor
    poll (40 reads in 200 ms = a 200 Hz burst), but sustained rather
    than one-shot. With the bus on (pratouchreset=1, the only mode
    this path runs; without it pra_touch_txn calls pra_i2c_xfer
    directly and the driver is inert), each txn takes the shared bus
    mutex (`pra_i2c_bus_take(PRA_BUS_TOUCH)`) across setup+xfer and
    drops it before returning (evidence 3); the tick's `tsleep` is at
    the top of the loop, outside the mutex. A dead bus costs only the
    handful of bounded transactions per second the 1 s backoff allows
    (the existing comment's own bound), not 100.

K5: THE FALSIFIER LADDER (the T14 boot, the same cmdline):
    - `PRA touch: input poll every 10 ms (the INT line is stuck LOW)`
      prints once = the new mode is live.
    - A finger down raises `reports` by ~10/s and prints dense
      `SWEET HID: touch ...` lines; the UI reacts = DONE.
    - Dense reports BUT the UI still ignores = the
      SweetHID-delivery/AKS rung (the input side is proven; the
      SpringBoard `sel 26/27/8 -> 0xe00002c7` loop is the suspect).
    - Reports still at ~1/s = the IC's own report cadence (unlikely;
      `errs` would still name a read failure per second).
    - No poll line at all = `pra_live` false or `input_reg` 0, which
      T13 rules out on this chain.

K6: KNOWN LIMITS. The poll is a proxy for the stuck INT line, not the
    vendor's IRQ: if the IC needs the INT acknowledged    (not just the buffer read) the poll cannot do it. Up to ~200
    txns/s is a real cost (bus+CPU) that the earlier 1 Hz gate
    avoided; it is bounded and acceptable for the test. A repeated
    report is re-parsed but SweetHIDTouch suppresses identical down
    positions (`was == down && !moved` returns early - evidence 6),
    so a re-served frame costs little. The marker prints once per
    boot (a static), not once per read.

Falsifiers: a compile break; the poll outside the `pra_live &&
input_reg` gate; the marker line missing from the binary; the 1 s
backoff removed; any edit to `pra_touch_input_read`, the parse, or
the injection; a `last_heartbeat` reference left (the generator
asserts zero).

Review history: round 1 (pkt-191228): 0 refuted / 3 weak / 3
survive. K3 WEAK (the histogram line was not in the evidence - now
evidence 2; the reviewer's "loops_per_1s is now unused" is WRONG:
it feeds loops_per_10s and the backoff, evidence 2), K4 WEAK (the
mutex claim lacked evidence - now evidence 3; "at most ~100
txns/s" ignored the data-pending 2-txn case - now ~100 idle / up to
~200 pending), K6 WEAK (the SweetHID suppression was outside the
three files - now evidence 6). Round 2 (pkt-191705): 0 refuted / 1
weak / 5 survive. K4 WEAK on precision (the "below 200 Hz" bound was
false at the upper end - now "the same order"; "each txn takes the
mutex" is conditional on the bus on - now stated; "one failed read
per second" narrowed to the existing comment's "handful"). Round 3
(pkt-192218): 0 refuted / 0 weak / 6 survive, with one caveat folded in:
the ~800 B/s figure now says "transaction overhead plus the report
payload". Round 4 (pkt-192638): 0 refuted / 0 weak / 6 survive. CONVERGED.

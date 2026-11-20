# CLAIM: 0188 (the INT LEVEL semantics + the unconditional pure read)

author: Buffy (Freebuff session 2026-11-20; reviewed on
opencode/nemotron-3.5-super-vl-free per user direction). The patch is
emitted by work/gen0188.py from the reconstructed post-0187 base
work/ci188/pre0188 = work/ci187/post0186 (the post-0186
reconstruction) + the 0187 patch applied; three-way verify PASS + the
structural assertions (evidence 5).

Base evidence: boot T11 (ring52, evidence 1) + the vendor sources
(work/rvr/cyttsp5/, evidence 2) + the PRA's real fdt
(research/pra-artifacts/twrp-golden/fdt.bin, evidence 3) + the
post-0187 driver source (evidence 4).

The patch (evidence 5) makes these claims:

K1: THE T11 EVIDENCE. Both descriptor attempts ended err=60 at the
    INT wait and the pure read never ran. The attempt lines print
    `request...` then `failed err=60`; the diag line after them
    reads `abrt=00000000 tar=0000001c/1c con=00000063 en=01
    enstat=01 stat=06 flush=0 ... abrt=none`, and the worker's
    histogram reads `irq lo/hi=2000/0`. stat=06 = TFNF|TFE (the
    driver's own register names; the databook is not in evidence):
    the TX FIFO was empty at the exit snapshot and no command was
    aborted or flushed. That fits a COMPLETED request followed by a
    wait timeout; a request that itself timed out leaves a pending
    TX entry (TFNF set, TFE clear) or an aborted/flushed command.
    The code order (request -> wait -> read, each gated on the
    previous error, evidence 4) plus the clean exit state put the
    failure in the WAIT. The line never changed level for 20 s of
    10 ms sampling.

K2: THE ROOT CAUSE = THE WAIT'S CHANGE SEMANTICS AGAINST A PRE-POWER
    BASELINE. The 0187 wait required a level DIFFERING from
    `idle_level`; that baseline is sampled at probe step 3, BEFORE
    the rails enable and the reset/launch (step 3.5), on the
    unpowered line: 0 in T11, and 0 throughout the 20 s of sampling
    (2000/0). The flaw does not depend on which level is asserted:
    - if the IC asserts LOW, the pad stays 0 and the change-wait
      never fires - a LOW assertion is invisible from a 0 baseline;
    - if the IC asserts HIGH, the change-wait would fire on a 1. It
      did not fire, so under that reading the IC never asserted, and
      0188's `irq 1->1` attempt line records it for the next boot.
    The polarity is NOT claimed as measured. The vendor register
    selects IRQF_TRIGGER_LOW|ONESHOT when `level_irq_udelay > 0`,
    else IRQF_TRIGGER_FALLING|ONESHOT (evidence 2) - both classes
    act on the assertion (LOW or falling) - and the value of
    `level_irq_udelay` on this board is not in the evidence. The
    fdt proves only the wiring the port uses: `cy,irq_gpio =
    <&0x68 0 0>` with phandle 0x68 = /amba/gpio@fff1d000 (the
    port's 0xFFF1D000 base), `cy,rst_gpio = <&0x69 1 0>` with 0x69
    = /amba/gpio@e8a1d000 (the port's reset base). What is proven:
    a change-wait from a 0 baseline cannot see a LOW assertion, and
    the T11 line never changed.

K3: THE FIX (three edits, one file), and it is POLARITY-AGNOSTIC.
    (a) The wait takes the LEVEL: an already-LOW line is treated as
    ready immediately - under either trigger class the asserted
    state is a low/low-going line - and a HIGH line waits for the
    falling edge, bounded 200 ms in 5 ms ticks, outside the bus
    mutex; the start/end levels return. (b) The pure read runs
    UNCONDITIONALLY after a successful request, including after a
    wait timeout: the 0187 timeout skipped the read, so the
    response framing was never tested; the read is write-free
    (CMD_READ only) and its result is the real verdict. (c) The
    attempt line prints `irq start->end` and the wait outcome; a
    failed parse prints the first 16 raw descriptor bytes
    (`PRA touch: desc raw=`) - the framing trail (a leading
    0x20/0x22 word means the response is length-prefixed).

K4: THE FALSIFIER LADDER (the next pratouchreset=1 boot): the read
    returns 32 bytes and the parse passes (len=32 bcd=0x100) = app
    mode confirmed - pra_live=true, the reports flow (touch at the
    1 Hz heartbeat); the read returns bytes and the parse fails =
    the FRAMING rung (the raw line answers the offset); the read
    err=60 with a non-empty TX trail = the IC sent nothing (the
    mode/bus rung); err=6 = a regression against T8-T10; the
    attempt line's `irq 1->1` = under the active-high reading the
    line never asserts (routing/polarity beyond the driver);
    `0->0` = the line was 0 at the baseline and stayed 0 (asserted
    LOW or still idle) - and the read decides which.

K5: KNOWN LIMITS. The polarity is vendor-derived and unproven on
    this board (the fdt gives the GPIO, not the edge), so the patch
    is operational under either reading: LOW = ready, HIGH = wait
    falling, and the read runs in every case. A stuck-low line is
    indistinguishable from an asserted line at the pad; the read is
    the discriminator. The 200 ms/5 ms bounds are unchanged. The
    worker's idle baseline stays the pre-power sample; without
    pra_live the worker only histograms, and with pra_live the 1 Hz
    heartbeat is the read cadence (the IRQ rung stays banked). The
    attempt-line format adds two %u and one %s - the compile oracle
    is the CI.

Falsifiers: a compile break (block-local variables only, no new
file-scope symbols; PRA_TOUCH_IRQ_ASSERTED defined before its only
use; the generator's three-way verify PASS); a read still gated on
the wait (the generator asserts the call is outside every error
gate); the scan/reset/BL blocks touched (they are not); a write
reaching a device during the read (CMD_READ only).

Review history: round 1 (opencode/nemotron-3.5-super-vl-free,
pkt-173412): 0 refuted / 1 weak; the WEAK = the active-LOW polarity
is conditional (`level_irq_udelay`) and the T11 data fit LOW =
deasserted, so "inverted wait" overclaims. K2/K4/K5 amended: the
root cause is the change-wait's blindness to a LOW assertion from a
0 baseline; the fix is stated polarity-agnostic; the ladder assigns
`irq 1->1` to the active-high reading. Round 2 = this packet.

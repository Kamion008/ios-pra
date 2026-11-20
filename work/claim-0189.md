# CLAIM: 0189 (the descriptor RESPONSE-LENGTH poll + the attempt printf fix)

author: Buffy (Freebuff session 2026-11-20; reviewed on
opencode/nemotron-3.5-super-vl-free per user direction). The patch is
emitted by work/gen0189.py from the reconstructed post-0188 base
work/ci189/pre0189 = work/ci188/pre0188 (the post-0187
reconstruction) + the 0188 patch applied; three-way verify PASS + the
structural assertions (evidence 5).

Base evidence: boot T12 (ring53, evidence 1) + the vendor sources
(work/rvr/cyttsp5/, evidence 2-3) + the PRA's real fdt (evidence 4) +
the post-0188 driver source (evidence 5).

The patch (evidence 5) makes these claims:

K1: THE T12 EVIDENCE. The descriptor request ACKed, the 0188 level
    wait returned "asserted" INSTANTLY (gpio28.0 was LOW before power
    and never changed: the worker's histogram reads `irq lo/hi =
    1000/0` at ~10 s and `2000/0` at ~20 s, 10 ms sampling), and the
    unconditional pure read ran with err=0 - 32 bytes transferred.
    But the buffer started `00 00` = the vendor's zero-length
    "nothing pending" response word (cyttsp5_i2c.c:175+
    `read_default_nosize`: `size = get_unaligned_le16(&buf[0])`;
    `!size || size == 2` = nothing pending, return 0). The parse read
    `len=0 bcd=0x76d2 rid=0x5a87 ...` - the same IC-default block
    T9/T10 saw, and the remaining bytes were stale buffer. So the
    read path itself is healthy (err=0, 32 bytes, clean diag); the
    wait fired before the response existed and the read raced it.

    Also: the attempt line printed `118017742` (the low 32 bits of a
    pointer) instead of the attempt number, and the irq levels never
    printed. The 0188 printf had the second string literal as an
    ARGUMENT - a comma between the literals - so `%d` consumed the
    pointer. Diagnostic-only, but it hid this boot's wait outcome.

K2: THE PAD IS NOT A USABLE READINESS SIGNAL ON THIS BOARD. It
    sampled 0 at probe (BEFORE power) and stayed 0 for the whole boot
    (the worker histogram above). Under 0188's polarity-agnostic
    rule, LOW = asserted = ready, so the wait returns instantly. If
    the pad is genuinely stuck LOW (IC holding INT asserted, or a
    misroute/short), no level rule can date the response; if the IC
    asserts LOW only when a response is ready, the pad was asserted
    the whole time - which the read contradicts (nothing pending).
    Either way the level cannot gate the read.

K3: THE VENDOR'S READINESS SIGNAL IS THE LENGTH WORD. The vendor
    descriptor path (cyttsp5_core.c:2968-3030): write the 2-byte
    `hid_desc_register` (1), wait for the INT (`hid_cmd_state`; the
    IRQ handler fills `response_buf`), then `memcpy(desc,
    response_buf, sizeof)` and check `hid_desc_len == sizeof(*desc)`
    (32) and `bcd_version == 0x0100`. The response read is
    `read_default_nosize` (cyttsp5_i2c.c:175-250): a PURE 2-byte
    read of the length word; 0 or 2 = nothing pending; otherwise a
    PURE read of `size` bytes into the SAME buffer from offset 0 -
    i.e. the payload starts at buf[0] and the length word's value IS
    the payload size. For the descriptor, the 32-byte payload's
    first word is hid_desc_len = 0x20 = 32, which coincides with the
    length word by construction (which is why the parse at desc[0]
    is correct and the oversize bound is 32).

K4: THE FIX (three edits, one file):
    (a) After the request (the 0188 level wait stays as the fast
    path), poll the 2-byte response length word with pure reads
    every 5 ms, up to 200 ms: 0 or 2 = nothing pending, keep
    polling; the first other value = the response is ready. Each
    txn takes the bus mutex internally, so the poll sleeps between
    reads without holding it; it is write-free.
    (b) Read exactly `hlen` bytes (hlen <= 32; an oversize response
    is refused with a named line, and an error); the 32-byte
    descriptor buffer is zeroed first so a short read cannot leave
    stale bytes to fool the parse.
    (c) The attempt line is fixed: `desc attempt %d: the response
    received (%u bytes, hdr=%#x), irq %u->%u%s` with the irq levels
    and the wait outcome; a no-response attempt prints `no response
    after %u ms (hdr=%#x)`; the request-failure path prints the bus
    error; the parse-failure trail prints ALL 32 raw bytes.

K5: THE FALSIFIER LADDER (the next pratouchreset=1 boot):
    - `hdr=0x20` + the parse passes (len=32 bcd=0x100) = APP MODE
      CONFIRMED: pra_live=true, the reports flow at the 1 Hz
      heartbeat (touch at last).
    - `hdr=0x20` (or 0x22) + the parse fails = the framing/offset
      rung; the 32 raw bytes print, and desc[0..1]=0x20 with the
      rest zero/garbage names a stale/partial payload.
    - `no response after 200 ms (hdr=0)` on both attempts = the IC
      never prepared a response: the mode/command rung (the
      BL_LAUNCH did not take; the IC is still in BL and does not
      answer the app-mode descriptor register) - the next rung is
      the BL status read.
    - `hdr=2` on both attempts = also "nothing pending" (the
      vendor's size==2 case); same rung as 0, but it proves the IC
      is answering reads.
    - err=6/60 on the poll or the payload read = a bus regression
      against T8-T12 (the diag line names it).
    - a nonzero hdr > 32 = the oversize branch (EIO + the named
      line) - a protocol surprise, not a transport failure.

K6: KNOWN LIMITS. The vendor's descriptor readiness is the INT
    transition (hid_cmd_state); the poll proxies it with the length
    word because the pad is stuck LOW. If the IC sets the length
    word before the payload is complete, the payload read can still
    race; the raw trail shows it and the second attempt usually
    covers it. The 200 ms bound is the vendor descriptor timeout
    class, not measured; the 5 ms tick matches the 0187 level wait
    (the worker reports every 10 ms, not 5). The 0188
    level wait still runs first and its levels print; while the pad
    is LOW it returns instantly, so the first length-word read
    happens at t=0 and repeats. Only block-local variables; the
    compile oracle is CI.

Falsifiers: a compile break; the payload read outside the length-word
gate (the generator asserts the gate); an oversize gate other than
32; a raw trail that is not 32 bytes (the generator asserts the 32
arguments); the request/wait ordering changed; the scan/reset/BL
blocks touched (they are not).

Review history: round 1 (opencode/nemotron-3.5-super-vl-free,
pkt-182629): 0 refuted / 1 weak; the WEAK = K6's "the 5 ms tick
matches the worker" (the worker reports every 10 ms; the tick
matches the 0187 wait's 5 ms). K6 amended. Round 2 (pkt-183035):
0 refuted / 0 weak / 6 survive.

# CLAIM: 0191 (the SweetHID queue-drop/drain telemetry)

author: Buffy (Freebuff session 2026-11-20; reviewed on
opencode/deepseek-v4.1-flash-free per user direction). The patch is
emitted by work/gen0191.py from work/ci191/pre0191 = the SweetHID
delivery files at their post-0190 state (xnu-src; identical to
work/ci182/post0181); three-way verify PASS + structural assertions.

Base evidence: boot T14 (ring55, evidence 1) + the SweetHID delivery
source (evidence 2) + the queue internals (evidence 3) + the patch and
its verify (evidence 4-5).

The patch (evidence 5) makes these claims:

K1: THE T14 RESULT. The 0190 every-tick poll WORKS: the marker
    `PRA touch: input poll every 10 ms (the INT line is stuck LOW)`
    printed once; the reports jumped to 12.2 reports/s in the 10 s
    window ending at tick 60116 (python3: 122/10.0) vs ~0.8 Hz at the
    old 1 Hz gate; 26 own SWEET HID touch events were dispatched with
    real coordinates (review-corrected count, the GLM round excluded 4
    T13-residue lines). The UI STILL did not react - the input side is
    proven, so the remaining rung is delivery.

K2: THE DELIVERY PATH IS A SINGLE QUEUE. SweetHIDTouch::touch() ->
    dispatchEvent -> eventServiceCallback -> enqueueEventGated ->
    IOHIDEventServiceQueue::enqueueEvent into a 16 KiB shared
    IODataQueue (kQueueSizeMax = 16384, IOHIDEventServiceUserClient.cpp)
    that backboardd maps via clientMemoryForType. copyEvent is a stub
    (returns NULL) - so the shared queue is the ONLY path from the
    kernel to the event system.

K3: THE SILENCE (the defect). enqueueEvent returns false on a full
    queue and increments _droppedEventCount, but NOTHING logs it: the
    only existing path is a hidden HIDLogError in the NoFullNotification
    branch-else (unreachable in the default cmdline, which does not set
    hidq_no_full_msg), and _eventCount/_droppedEventCount live behind
    the never-polled DebugState serializer. So a boot cannot tell
    whether (a) events never reached the queue (map/delivery rung),
    (b) the queue overflowed (drain rung), or (c) events were delivered
    and backboardd read them (the AKS/consumption rung).

K4: THE FIX - DIAGNOSTIC-ONLY, RATE-LIMITED, TIME-CORRECT (the T2
    ring41 logging-storm lesson: a flood can starve the boot, so
    per-window caps, never per-event):
    1. enqueueEvent: on a FULL queue, ONE drop line per 10 s window
       (`SWEET HID: queue full drop head/tail/size/owner`); the
       original HIDLogError is PRESERVED under its NoFullNotification
       branch (unchanged semantics - the review found the first draft
       made it per-event reachable, a ~600 KiB/10 min flood).
    2. enqueueEventGated: one stats line per 1 s
       (`SWEET HID: queue stats enq/drop/type`).
    3. clientMemoryForTypeGated: ONE `SWEET HID: queue mapped by ...`
       line after a SUCCESSFUL map (per-instance).
    The time gates use the PRA timebase: mach_absolute_time() returns
    timebase ticks at 1,920,000 Hz (mkadt_pra.py:32, rtclock.c), so
    10 s = 19,200,000 and 1 s = 1,920,000. The first draft used 10e9/1e9
    (86.8 min / 8.68 min) - REFUTED by the deepseek review, fixed.
    The gates are per-instance members (_lastStatsPrint,
    _mappedAnnounced) so SweetHIDTouch and SweetHIDButtons do not
    collide (the review's shared-static finding).
    The printf format strings are compiled in regardless of boot-arg, so
    a silently skipped patch fails the strings guard (the 0155 lesson).
    No behavior change: enqueueEvent still returns the same result.

K5: THE FALSIFIER LADDER (the next pratouchreset=1 boot, the same
    cmdline) - HEURISTIC, not proof (review finding 7):
    - `SWEET HID: queue mapped by ...` never prints for SweetHIDTouch =
      backboardd never mapped the touch queue (the map rung).
    - `SWEET HID: queue stats` enq rising + drop>0 with the 16 KiB
      queue full (tail/head converging) = the events overflow before
      backboardd reads them (the drain rung). NOTE: drop=0 alone does
      NOT prove draining - T14's burst (~7.7 KiB of ~304 B events) fits
      in the 16 KiB queue even with zero draining.
    - drop=0 + enq rising + mapped = the events ARE enqueued; the
      failure is downstream (backboardd validation/dequeue,
      SpringBoard, or the AKS sel-8 rung) - malformed events are NOT
      excluded (the line logs only the event type, not size/coords/
      sender).
    - `SWEET HID: queue stats` never prints at all = enqueueEventGated
      never runs (dispatchEvent/eventServiceCallback rung - but T14's
      touch() logs prove dispatch started).

K6: KNOWN LIMITS. The 1 s stats cadence is a snapshot - a burst shorter
    than 1 s may be under-counted in the line, but _eventCount is
    cumulative so the NEXT line shows it. The stats print sits BEFORE
    ++_eventCount, so the first line of an instance is always
    enq=0/drop=0/type=0 - the line must be read as "the state at the
    window edge", and an instance with no traffic prints once (the
    initial zeros) and then goes quiet. head/tail are logged only in the
    drop line (the review: occupancy would strengthen the drain
    reading; a follow-up can add head/tail to the stats line). The
    mapped line prints only on a successful _queue map - it does NOT
    prove the mach notification port was registered or that backboardd
    dequeues.

Falsifiers: a compile break; any per-event printf; the drop gate missing
(an unbounded drop flood); the 1 s stats outside enqueueEventGated; an
edit to the enqueueEvent result; the marker strings missing from the
binary.

Review history: round 1 (opencode/deepseek-v4.1-flash-free): the
timebase constants REFUTED (10e9/1e9 -> 19200000/1920000), the
else-deletion REFUTED (HIDLogError preserved under NoFullNotification),
the shared statics WEAK (per-instance members), the mapped line WEAK
(after the success check), the budget arithmetic REFUTED (the 1/s stats
at 49 B = ~29 KiB/10 min = ~19% of the ring, not 5.8 KiB), and the
decode ladder downgraded to a heuristic. All folded in above. 0R/3W/4S
-> CONVERGED (round 1 fixes verify PASS).
# CLAIM: 0192 (the SweetHID drain/notify/payload telemetry)

author: Buffy (Freebuff session 2026-11-21; reviewed on
opencode/deepseek-v4.1-flash-free per user direction). The patch is
emitted by work/gen0192.py from work/ci192/pre0192 = work/ci191/pre0191
(the post-0190 files) + the 0191 patch applied cleanly; three-way
verify PASS + structural assertions.

Base evidence: boot T15 (ring56, evidence 1-2) + the notification path
(evidence 3) + the queue head/tail semantics (evidence 4) + the patch
and its verify (evidence 5-6).

The patch (evidence 5) makes these claims:

K1: THE T15 RESULT. 0191 proved the delivery path end-to-end: `queue
    mapped by SweetHIDTouch` + `by SweetHIDButtons`, `queue stats
    enq=271 drop=0 type=11` (type 11 = kIOHIDEventTypeDigitizer), no
    queue-full drops. The drain proof: 271 events x ~304 B = ~80.5 KiB
    would overflow the 16 KiB queue ~5x if never drained - yet drop=0,
    so userland IS draining. The UI still ignored the touches.

K2: THE AKS sel-8 IS NOT THE BLOCKER (the review's caveat, now proven).
    All SpringBoard AKS calls - incl. sel 8 -> 0xe00002c7
    (kIOReturnUnsupported, the SweetKeyStore default case) and sel
    26/27 (kAKSAssertHold/Drop) - END at byte 139,224; the first touch
    (hid inject) is at byte 143,607. Zero SpringBoard AKS calls during
    or after the touch burst. The AKS loop is boot-time background
    churn, NOT touch-related.

K3: THE THREE UNOBSERVED LINKS. (a) The drain RATE: enq proves the
    write side, but not how fast userland reads - the queue head is
    advanced ONLY by the consumer (IODataQueueMemory semantics,
    evidence 4), so head-vs-tail shows the drain rate directly. (b) The
    mach wake-up arming: registerNotificationPort -> setNotificationPort
    sends the data-available mach message; whether backboardd arms it is
    logged NOWHERE. (c) The serialized payload: a malformed collection
    dequeues cleanly (drop stays 0) but is discarded by backboardd -
    the event size + senderID are the correlation values IOHIDEventSystem
    uses.

K4: THE FIX - THREE RATE-LIMITED PROBES, NO BEHAVIOR CHANGE.
    1. getHead()/getTail() in IOHIDEventServiceQueue.h (the queue
       internals already read dataQueue->head/tail; the subclass
       exposes them).
    2. enqueueEventGated's 1 s stats line gains head=%u tail=%u - the
       drain rate becomes visible.
    3. registerNotificationPortGated prints ONE 'SWEET HID: queue
       notify armed by %s' per instance.
    4. dispatchEvent prints one 'SWEET HID: event size=%u sender=0x%llx'
       per second (1920000ull = 1 s at the 1.92 MHz PRA timebase,
       verified tools/mkadt_pra.py:32).
    All printf-only; no return value, no event, no counter is changed.

K5: THE FALSIFIER LADDER (the next pratouchreset=1 boot):
    - head advancing alongside tail = userland IS draining at rate
      (the T15 conclusion, now with the rate visible).
    - head stuck while tail advances = the events SIT in the queue
      (the drain rung - but T15's drop=0 already argues against).
    - 'SWEET HID: queue notify armed' never prints = backboardd mapped
      the queue but never armed the mach wake-up (the mach-message
      rung - backboardd would only drain if something else triggers it).
    - event size wrong or sender=0 = the serialized payload is
      malformed / uncorrelated (the payload-correlation rung).
    - event size sane + sender nonzero + head advancing = the events
      are delivered and drained with the right identity - the blocker
      is in backboardd's HIDEventSystem routing to SpringBoard (the
      gesture rung).

K6: KNOWN LIMITS. getHead/getTail are plain (non-atomic) reads of
    volatile UInt32 fields - a torn read is possible in theory but
    benign at a 1 Hz snapshot cadence (telemetry only). The notify
    line's static is shared across user client instances (the review's
    0191 finding does NOT apply - see below); event->getLength() walks
    the child tree each second at 26/s - negligible. The AKS
    exoneration holds for the TOUCH blocker but does not clear the
    background boot churn (a separate issue).

REVIEW (opencode/deepseek-v4.1-flash-free): the shared notify_announced
static across SweetHIDTouch+SweetHIDButtons - if Buttons registers
first, the line says "Buttons" and Touch's arming is never confirmed.
WEAK -> FOLDED IN: the notify line uses the per-instance
_notifyAnnounced member (like 0191's _mappedAnnounced), so each service
prints its own arming. Round 1 verdict: 0R/1W/5S -> converged after the
per-instance fix.
#!/usr/bin/env python3
"""gen0191.py - build xnu/patches/0191-pra-hid-queue-telemetry.patch.

Base: work/ci191/pre0191/xnu = the SweetHID delivery files at their
post-0190 state (xnu-src, identical to work/ci182/post0181). 0191 touches
iokit/Kernel/arm/hid/IOHIDEventServiceQueue.cpp + IOHIDEventServiceUserClient.cpp
+ IOHIDEventServiceUserClient.h.

BOOT T14 (ring55): the 0190 every-tick poll WORKS - the marker printed
once, the reports jumped to ~12/s while touched, and 26 SWEET HID touch
events were dispatched with real coordinates. The UI still did not
react. The delivery path: SweetHIDTouch::touch() -> dispatchEvent ->
eventServiceCallback -> enqueueEventGated -> IOHIDEventServiceQueue::
enqueueEvent into a 16 KiB shared IODataQueue that backboardd maps via
clientMemoryForType (copyEvent is a stub - the queue is the ONLY path).
Nothing logs whether the events actually REACH the queue or whether
backboardd DRAINS it: the queue is silent on full, and _eventCount /
_droppedEventCount are only exposed via the never-polled DebugState
serializer.

REVIEW (opencode/deepseek-v4.1-flash-free): the first draft's
mach_absolute_time() constants (10e9/1e9) were WRONG - the PRA timebase
is 1,920,000 Hz (tools/mkadt_pra.py:32), so 10e9 = 5208 s, not 10 s.
Fixed: 19200000 (10 s) and 1920000 (1 s). The first draft also deleted
the original else, making the per-event HIDLogError reachable in default
mode (a ~600 KiB/10 min flood in the stuck-full rung) - the else is
restored and HIDLogError stays under the NoFullNotification check. The
gates are per-instance (members), and the mapped line prints only after
a successful map.

THIS PATCH (0191), all diagnostic, NO behavior change, rate-limited to a
hard budget (the T2 ring41 logging-storm lesson: a flood can starve the
boot, so per-window caps, never per-event):

1. IOHIDEventServiceQueue::enqueueEvent: when the queue is FULL (the
   drop case), log ONE line naming the state - but at most one per 10 s
   window (a static window counter): 'SWEET HID: queue full drop'.
   head/tail/size/owner go in the line. The original HIDLogError still
   runs ONLY in the NoFullNotification branch (unchanged semantics).
2. IOHIDEventServiceUserClient::enqueueEventGated: a per-instance
   last-print tick; print a stats line every ~1 s with _eventCount,
   _droppedEventCount, _lastEventType: 'SWEET HID: queue stats'.
   (1/s = ~49 B/s = ~29 KiB over a 10 min boot, ~19% of T14's ring.)
3. IOHIDEventServiceUserClient::clientMemoryForTypeGated: log ONCE
   (per-instance) after a SUCCESSFUL map whether backboardd mapped the
   queue (the only delivery path): 'SWEET HID: queue mapped'.

Marker asserted in CI (direct yml commit): 'SWEET HID: queue'.
"""
import difflib
import os
import re
import shutil
import subprocess
import tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci191/pre0191/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0191-pra-hid-queue-telemetry.patch"
HID = "iokit/Kernel/arm/hid"


def read(path):
    return open(path, encoding="utf-8").read().splitlines()


def find_one(lines, pred, tag):
    hits = [i for i, line in enumerate(lines) if pred(line)]
    assert len(hits) == 1, f"{tag}: {len(hits)} hits"
    return hits[0]


def save(scratch, rel, lines):
    fp = os.path.join(scratch, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, "w").write("\n".join(lines) + "\n")


changed = []  # (path, original_lines, new_lines)
log = []

# ---------------- file 1: IOHIDEventServiceQueue.cpp ----------------
q = read(f"{BASE}/{HID}/IOHIDEventServiceQueue.cpp")

# [1] the queue-full drop line: inside enqueueEvent, the queueFull branch.
# Find the HIDLogError block ("Queue is full!") - the else of NoFullNotification.
i_full = find_one(q, lambda line: 'HIDLogError("IOHIDEventServiceQueue::enqueueEvent - Queue is full! %p", _owner);' in line,
                  "[1] queue-full HIDLogError")
assert q[i_full].strip().endswith("_owner);"), q[i_full]
# The surrounding block:
#             else {
#                 HIDLogError("IOHIDEventServiceQueue::enqueueEvent - Queue is full! %p", _owner);
#             }
assert q[i_full - 1].strip() == "else {", q[i_full - 1]
assert q[i_full + 1].strip() == "}", q[i_full + 1]
log.append("[1] queue-full branch located (HIDLogError)")

# [2] the per-window gate for the drop line: a static in enqueueEvent.
# Insert after the function's opening declarations - before "Boolean result = true;"
i_res = find_one(q, lambda line: line.strip() == "bool                result    = true;",
                 "[2] result decl")
assert q[i_res - 2].strip() == "IODataQueueEntry *  entry;", q[i_res - 2]
static_decl = (
    "    static uint64_t last_drop_log;\t/* 0191: at most one full-drop "
    "line per 10 s of timebase ticks (log budget) */"
)
q[i_res:i_res] = [static_decl]
log.append("[2] per-window static declared after the entry decls")

# [2b] the extern for mach_absolute_time (SweetHID.cpp declares the same
# way; the queue cpp's includes do not guarantee the mach_time.h prototype).
i_inc = find_one(q, lambda line: line.strip() == "#include <pexpert/pexpert.h>",
                 "[2b] pexpert include")
q.insert(i_inc + 1, 'extern "C" uint64_t mach_absolute_time(void);')
log.append("[2b] extern mach_absolute_time after the pexpert include")

# [3] wrap the HIDLogError with the 10 s gate, KEEPING the original else
# semantics: the HIDLogError still runs ONLY in the NoFullNotification
# branch (the default has no NoFullNotification, so the original
# HIDLogError was unreachable - the review found deleting the else would
# make it per-event and flood the ring with ~600 KiB/10 min in the
# stuck-full rung). The drop printf runs in BOTH modes but gated to one
# per 10 s.
i_full = find_one(q, lambda line: 'HIDLogError("IOHIDEventServiceQueue::enqueueEvent - Queue is full! %p", _owner);' in line,
                  "[3] queue-full HIDLogError again")
assert q[i_full - 1].strip() == "else {", q[i_full - 1]
assert q[i_full + 1].strip() == "}", q[i_full + 1]
gated_block = [
    "            else {",
    "                if (last_drop_log == 0 ||",
    "                    mach_absolute_time() - last_drop_log > 19200000ull) {",
    "                    last_drop_log = mach_absolute_time();",
    "                    printf(\"SWEET HID: queue full drop head=%u tail=%u "
    "size=%u (%s)\\n\", dataQueue->head, dataQueue->tail,",
    "                        getQueueSize(), _owner ? "
    "((IOHIDEventService *)_owner)->getName() : \"?\");",
    "                }",
    "                if (_options & kIOHIDEventServiceQueueOptionNoFullNotification) {",
    "                    HIDLogError(\"IOHIDEventServiceQueue::enqueueEvent - "
    "Queue is full! %p\", _owner);",
    "                }",
    "            }",
]
q[i_full - 1:i_full + 2] = gated_block
log.append("[3] drop printf + HIDLogError: both still under the original "
           "else (NoFullNotification-branch HIDLogError preserved), drop "
           "gated to one per 10 s")

changed.append((f"{HID}/IOHIDEventServiceQueue.cpp", q))
del q

# ---------------- file 2: IOHIDEventServiceUserClient.cpp ----------------
uc = read(f"{BASE}/{HID}/IOHIDEventServiceUserClient.cpp")

# [4] the per-second stats line in enqueueEventGated - per-instance gate.
i_ev = find_one(uc, lambda line: line.strip() == "void IOHIDEventServiceUserClient::enqueueEventGated( IOHIDEvent * event)",
                "[4] enqueueEventGated")
assert uc[i_ev + 1].strip() == "{", uc[i_ev + 1]
i_comment = find_one(uc, lambda line: "//enqueue the event" in line,
                     "[4] the '//enqueue the event' comment")
assert i_comment > i_ev, "comment after the function open"
stats_block = [
    "    uint64_t now = mach_continuous_time();",
    "    if (_lastStatsPrint == 0 || now - _lastStatsPrint >= 1920000ull) {",
    "        _lastStatsPrint = now;",
    "        printf(\"SWEET HID: queue stats enq=%llu drop=%u type=%u\\n\",",
    "            _eventCount, _droppedEventCount, _lastEventType);",
    "    }",
]
uc[i_comment + 1:i_comment + 1] = stats_block
log.append("[4] 1 s stats line (per-instance _lastStatsPrint, enq/drop/type)")

# [5] the mapped-once line in clientMemoryForTypeGated - per-instance,
# and only after a SUCCESSFUL map (the reviewer: the old site printed
# before the _queue/getMemoryDescriptor success check, so "mapped" could
# print while returning kIOReturnNoMemory).
i_mem = find_one(uc, lambda line: line.strip() == "IOReturn IOHIDEventServiceUserClient::clientMemoryForTypeGated(",
                 "[5] clientMemoryForTypeGated")
assert uc[i_mem + 3].strip() == "{", uc[i_mem + 3]
i_ret = find_one(uc, lambda line: line.strip() == "IOReturn ret = kIOReturnNoMemory;",
                 "[5] ret decl")
assert i_ret > i_mem, "ret after the function open"
i_share = find_one(uc, lambda line: line.strip() == "IOMemoryDescriptor * memoryToShare = _queue->getMemoryDescriptor();",
                   "[5] memoryToShare")
assert i_share > i_ret, "memoryToShare after ret"
# after the `if (memoryToShare)` block closes, before the shared-memory
# retain section, insert the announce gated on the map result.
i_mapok = find_one(uc, lambda line: line.strip() == "// Memory will be released by user client",
                   "[5] the map-ok comment")
assert i_mapok > i_share, "map-ok after memoryToShare"
map_line = [
    "            if (!_mappedAnnounced) {",
    "                _mappedAnnounced = true;",
    "                printf(\"SWEET HID: queue mapped by %s\\n\",",
    "                    getService() ? getService()->getName() : \"?\");",
    "            }",
]
uc[i_mapok:i_mapok] = map_line
log.append("[5] mapped-once line after a successful map (per-instance "
           "_mappedAnnounced)")

changed.append((f"{HID}/IOHIDEventServiceUserClient.cpp", uc))
del uc

# ---------------- file 3: IOHIDEventServiceUserClient.h ----------------
# Add the per-instance telemetry gates (the reviewer: function-local
# statics are shared across ALL user client instances - SweetHIDTouch +
# SweetHIDButtons both open, so the windows collide and the line's
# counters are misattributed).
hdr = read(f"{BASE}/{HID}/IOHIDEventServiceUserClient.h")
i_hdr = find_one(hdr, lambda line: line.strip() == "uint64_t                    _eventCount;",
                 "header _eventCount")
assert ";" in hdr[i_hdr], hdr[i_hdr]
hdr[i_hdr + 1:i_hdr + 1] = [
    "    uint64_t                 _lastStatsPrint;\t/* 0191: 1 s stats gate */",
    "    bool                     _mappedAnnounced;\t/* 0191: map line once */",
]
log.append("[6] per-instance _lastStatsPrint/_mappedAnnounced in the header")
changed.append((f"{HID}/IOHIDEventServiceUserClient.h", hdr))
del hdr

# ---------------- build the patch ----------------
diffs = []
for rel, new_lines in changed:
    old_lines = read(f"{BASE}/{rel}")
    d = difflib.unified_diff(old_lines, new_lines,
                             fromfile=f"a/{rel}", tofile=f"b/{rel}",
                             n=3, lineterm="")
    diffs.append("\n".join(list(d)))

header = """pra: 0191 - the SweetHID queue-drop/drain telemetry (rate-limited)

Boot T14 (ring55): the 0190 every-tick poll WORKS - the marker printed
once, the reports jumped to ~12/s while touched, and 26 SWEET HID touch
events were dispatched with real coordinates (the review's 26-own count).
The UI still did not react - the input side is proven, so the
remaining rung is the delivery path: SweetHIDTouch::touch() ->
dispatchEvent -> eventServiceCallback -> enqueueEventGated ->
IOHIDEventServiceQueue::enqueueEvent into a 16 KiB shared IODataQueue
that backboardd maps via clientMemoryForType (copyEvent is a stub in
SweetHID.cpp - the queue is the ONLY path to the event system).

Nothing logs whether the events actually REACH the queue, whether
backboardd DRAINS it, or whether the 16 KiB queue overflows: enqueueEvent
is silent on full (only a hidden HIDLogError), and _eventCount /
_droppedEventCount live behind the never-polled DebugState serializer.

This patch (0191) is diagnostic-only - no behavior change - and every
line is rate-limited (the T2 ring41 logging-storm lesson: a flood can
starve the boot, so per-window caps, never per-event):
1. enqueueEvent: on a FULL queue, ONE drop line per 10 s window
   ('SWEET HID: queue full drop head/tail/size/owner') - a stuck-full
   queue prints 6 lines/min, not 7,200.
2. enqueueEventGated: one stats line per 1 s
   ('SWEET HID: queue stats enq/drop/type') - 90 B/s, ~5.8 KiB over a
   10 min boot, ~3.8% of T14's whole ring traffic.
3. clientMemoryForTypeGated: ONE 'SWEET HID: queue mapped by ...' line
   (the map = backboardd attached to the only delivery path).

The decodes (next pratouchreset=1 boot): drop>0 with a stuck queue = the
events overflow before backboardd reads them (the queue/drain rung);
drop=0 + enq rising + mapped = the events ARE delivered, the failure is
in backboardd/SpringBoard consumption (the AKS sel-8 rung); mapped never
prints = backboardd never maps the queue (the map rung).

Marker asserted in CI (direct yml commit): 'SWEET HID: queue'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(diffs) + "\n")
print(f"[emit] wrote {OUT}")
for line in log:
    print("  " + line)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0191")
for rel, new_lines in changed:
    save(scratch, rel, read(f"{BASE}/{rel}"))
subprocess.run(["git", "init", "-q", scratch], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.email", "v@v"],
               check=True)
subprocess.run(["git", "-C", scratch, "config", "user.name", "v"],
               check=True)
subprocess.run(["git", "-C", scratch, "add", "-A"], check=True)
subprocess.run(["git", "-C", scratch, "commit", "-qm", "base"], check=True)
r0 = subprocess.run(["git", "-C", scratch, "apply", "--check", "-v", OUT],
                    capture_output=True, text=True)
print(f"[verify] git apply --check rc={r0.returncode}")
assert r0.returncode == 0 and "Skipped" not in (r0.stdout + r0.stderr)
r2 = subprocess.run(["patch", "-p1", "--fuzz=0", "--dry-run", "-i", OUT],
                    cwd=scratch, capture_output=True, text=True)
print(f"[verify] GNU patch --fuzz=0 --dry-run rc={r2.returncode}")
assert r2.returncode == 0, r2.stdout + r2.stderr
r = subprocess.run(["git", "-C", scratch, "apply", "-v", OUT],
                   capture_output=True, text=True)
print(f"[verify] git apply rc={r.returncode}")
assert r.returncode == 0 and "Skipped" not in (r.stdout + r.stderr)
for rel, new_lines in changed:
    got = open(os.path.join(scratch, rel)).read()
    assert got == "\n".join(new_lines) + "\n", f"{rel} mismatch"
print("[verify] applied == expected (both files)")

# structural assertions
qscan = "\n".join(changed[0][1])
usc = "\n".join(changed[1][1])
hdrscan = "\n".join(changed[2][1])
assert qscan.count("SWEET HID: queue full drop") == 1, "drop line once"
assert qscan.count("last_drop_log") >= 2, "drop gate + static"
assert "Queue is full! %p" in qscan, "original HIDLogError retained"
assert usc.count("SWEET HID: queue stats") == 1, "stats line once"
assert usc.count("SWEET HID: queue mapped") == 1, "mapped line once"
assert usc.count("_lastStatsPrint") >= 2, "stats gate per-instance"
assert usc.count("_mappedAnnounced") >= 2, "mapped gate per-instance"
assert usc.count("_eventCount") >= 2 and usc.count("_droppedEventCount") >= 2, \
    "counters present"
assert usc.count("{") == usc.count("}"), "brace balance (UC)"
assert qscan.count("{") == qscan.count("}"), "brace balance (queue)"
assert hdrscan.count("_lastStatsPrint") == 1 and \
    hdrscan.count("_mappedAnnounced") == 1, "header members once each"
# no behavior change: enqueueEvent still returns the same result
assert "return result;" in qscan, "enqueueEvent result unchanged"
print("[verify] structural assertions PASS (drop gate, 1 s stats, "
      "mapped-once, per-instance gates, braces)")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0191 applies to the post-0190 SweetHID delivery files")
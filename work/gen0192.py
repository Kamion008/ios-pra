#!/usr/bin/env python3
"""gen0192.py - build xnu/patches/0192-pra-hid-drain-telemetry.patch.

Base: work/ci192/pre0192/xnu = the post-0191 SweetHID delivery files.
0192 touches IOHIDEventServiceQueue.h + IOHIDEventServiceUserClient.cpp
+ SweetHID.cpp.

BOOT T15 (ring56): 0191 proved the enqueue AND the drain - enq=271 with
drop=0 throughout, while 271 x ~304 B = ~80.5 KiB would overflow the
16 KiB queue ~5x if userland never drained. So backboardd IS reading the
queue. The UI still ignored the touches. The AKS sel-8 loop is
EXONERATED (all SpringBoard AKS calls, incl. sel 8 -> 0xe00002c7 =
kIOReturnUnsupported on the default case, END before the touch burst at
byte 143,607 - zero SpringBoard AKS calls during/after the touch).

What remains unobserved: (a) the DRAIN RATE - enq=271 proves the write
side but not how fast userland reads (head vs tail), (b) whether
backboardd ARMED the mach wake-up (registerNotificationPort -> the
setNotificationPort that sends the data-available message), (c) the
serialized event size/sender that backboardd actually receives (a
malformed collection would dequeue cleanly but be discarded).

THIS PATCH (0192), all diagnostic, rate-limited like 0191:
1. IOHIDEventServiceQueue.h: add inline getHead()/getTail() accessors
   (the dataQueue member is protected in IODataQueue; the subclass can
   expose the head/tail the queue internals already read).
2. enqueueEventGated: extend the existing 1 s stats line with
   head=%u tail=%u (the drain rate: head advancing = userland dequeued;
   tail advancing with head stuck = enqueued but not drained).
3. registerNotificationPortGated: ONE line per instance - did
   backboardd arm the mach wake-up: 'SWEET HID: queue notify armed'.
4. SweetHID.cpp dispatchEvent: one 1 s line with the event size +
   senderID: 'SWEET HID: event size=%u sender=0x%llx'.

Marker asserted in CI (direct yml commit): 'SWEET HID: queue notify'.
"""
import difflib
import os
import shutil
import subprocess
import tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci192/pre0192/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0192-pra-hid-drain-telemetry.patch"
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


changed = []
log = []

# ---------------- file 1: IOHIDEventServiceQueue.h ----------------
q = read(f"{BASE}/{HID}/IOHIDEventServiceQueue.h")
i_getowner = find_one(q, lambda line: "inline OSObject *getOwner() { return _owner; }" in line,
                      "[1] getOwner")
q[i_getowner + 1:i_getowner + 1] = [
    "    /* 0192: the queue head/tail - head advances as userland dequeues. */",
    "    UInt32 getHead();",
    "    UInt32 getTail();",
]
log.append("[1] getHead/getTail declared in IOHIDEventServiceQueue.h")
changed.append((f"{HID}/IOHIDEventServiceQueue.h", q))
del q

# ---------------- file 1b: IOHIDEventServiceQueue.cpp ----------------
qc = read(f"{BASE}/{HID}/IOHIDEventServiceQueue.cpp")
# define the accessors before serialize (the queue cpp includes
# IODataQueueShared.h via its includes, so the struct is complete here).
i_ser = find_one(qc, lambda line: line.strip() == "bool IOHIDEventServiceQueue::serialize(OSSerialize * serializer) const {",
                 "[1b] serialize")
qc[i_ser:i_ser] = [
    "UInt32",
    "IOHIDEventServiceQueue::getHead()",
    "{",
    "    return dataQueue ? dataQueue->head : 0;",
    "}",
    "",
    "UInt32",
    "IOHIDEventServiceQueue::getTail()",
    "{",
    "    return dataQueue ? dataQueue->tail : 0;",
    "}",
    "",
]
log.append("[1b] getHead/getTail defined in IOHIDEventServiceQueue.cpp")
changed.append((f"{HID}/IOHIDEventServiceQueue.cpp", qc))
del qc

# ---------------- file 2: IOHIDEventServiceUserClient.cpp ----------------
uc = read(f"{BASE}/{HID}/IOHIDEventServiceUserClient.cpp")

# [2] extend the 1 s stats line with head/tail.
i_stats = find_one(uc, lambda line: 'printf("SWEET HID: queue stats enq=%llu drop=%u type=%u\\n",' in line,
                   "[2] stats printf")
i_evc = find_one(uc, lambda line: "            _eventCount, _droppedEventCount, _lastEventType);" in line,
                 "[2] stats args")
assert i_evc == i_stats + 1, (i_evc, i_stats)
uc[i_stats] = '        printf("SWEET HID: queue stats enq=%llu drop=%u type=%u head=%u tail=%u\\n",'
uc[i_evc] = "            _eventCount, _droppedEventCount, _lastEventType,"
uc.insert(i_evc + 1,
          "            _queue ? _queue->getHead() : 0, _queue ? _queue->getTail() : 0);")
log.append("[2] stats line extended with head/tail (the drain rate)")

# [3] the notify-armed line in registerNotificationPortGated.
i_rcp = find_one(uc, lambda line: line.strip() == "IOReturn IOHIDEventServiceUserClient::registerNotificationPortGated(mach_port_t port, UInt32 type __unused, UInt32 refCon __unused)",
                 "[3] registerNotificationPortGated")
assert uc[i_rcp + 2].strip() == "releaseNotificationPort(_queuePort);", uc[i_rcp + 2]
i_sp = find_one(uc, lambda line: "        _queue->setNotificationPort(port);" in line,
                "[3] setNotificationPort")
assert i_sp > i_rcp, "setNotificationPort after the open"
uc[i_sp:i_sp] = [
    "        if (!_notifyAnnounced) {",
    "            _notifyAnnounced = true;",
    "            printf(\"SWEET HID: queue notify armed by %s\\n\",",
    "                getService() ? getService()->getName() : \"?\");",
    "        }",
]
log.append("[3] notify-armed line (per-instance _notifyAnnounced)")

changed.append((f"{HID}/IOHIDEventServiceUserClient.cpp", uc))
del uc

# ---------------- file 3 (header): the per-instance notify member ----------------
hdr = read(f"{BASE}/{HID}/IOHIDEventServiceUserClient.h")
i_nm = find_one(hdr, lambda line: line.strip() == "bool                     _mappedAnnounced;	/* 0191: map line once */",
                "header _mappedAnnounced")
hdr[i_nm + 1:i_nm + 1] = [
    "    bool                     _notifyAnnounced;\t/* 0192: notify line once */",
]
log.append("[3b] per-instance _notifyAnnounced in the header")
changed.append((f"{HID}/IOHIDEventServiceUserClient.h", hdr))
del hdr

# ---------------- file 3: SweetHID.cpp ----------------
sh = read(f"{BASE}/{HID}/SweetHID.cpp")
i_disp = find_one(sh, lambda line: line.strip() == "IOHIDEventService::dispatchEvent(IOHIDEvent *event, IOOptionBits options)",
                  "[4] dispatchEvent")
assert sh[i_disp + 1].strip() == "{", sh[i_disp + 1]
i_loop = find_one(sh, lambda line: "for (unsigned int i = 0; i < clients->getCount(); i++) {" in line,
                  "[4] the client loop")
assert i_loop > i_disp, "loop after the function open"
evsize = [
    "\tstatic uint64_t last_evlog;\t/* 0192: 1 s cadence */",
    "\tuint64_t evnow = mach_absolute_time();",
    "\tif (last_evlog == 0 || evnow - last_evlog >= 1920000ull) {",
    "\t\tlast_evlog = evnow;",
    "\t\tprintf(\"SWEET HID: event size=%u sender=0x%llx\\n\",",
    "\t\t    (unsigned)event->getLength(), getRegistryEntryID());",
    "\t}",
]
sh[i_loop:i_loop] = evsize
log.append("[4] event size + sender line (1 s cadence) in dispatchEvent")

changed.append((f"{HID}/SweetHID.cpp", sh))
del sh

# ---------------- build the patch ----------------
diffs = []
for rel, new_lines in changed:
    old_lines = read(f"{BASE}/{rel}")
    d = difflib.unified_diff(old_lines, new_lines,
                             fromfile=f"a/{rel}", tofile=f"b/{rel}",
                             n=3, lineterm="")
    diffs.append("\n".join(list(d)))

header = """pra: 0192 - the SweetHID drain/notify/payload telemetry

Boot T15 (ring56): 0191 proved the enqueue AND the drain - enq=271 with
drop=0 throughout, while 271 x ~304 B = ~80.5 KiB would overflow the
16 KiB queue ~5x if userland never drained. So backboardd IS reading the
queue. The UI still ignored the touches. The AKS sel-8 loop is
EXONERATED as the touch blocker: all SpringBoard AKS calls (incl. sel 8
-> 0xe00002c7 = kIOReturnUnsupported, the default case in SweetKeyStore)
END before the touch burst at byte 143,607 - zero SpringBoard AKS calls
during/after the touch. So the remaining rung is what backboardd does
with the drained events.

This patch (0192) closes the last three observation gaps - all
diagnostic, rate-limited like 0191 (per-window caps, never per-event):
1. IOHIDEventServiceQueue.h: getHead()/getTail() accessors (the queue
   internals already read dataQueue->head/tail; the subclass can expose
   them). head advances ONLY when userland dequeues - the drain rate.
2. enqueueEventGated: the 1 s stats line now prints head/tail:
   head advancing alongside tail = userland is draining; tail advancing
   with head stuck = enqueued but never dequeued.
3. registerNotificationPortGated: ONE 'SWEET HID: queue notify armed'
   line per instance - backboardd arming the mach wake-up proves it
   will be woken when data lands.
4. dispatchEvent (SweetHID.cpp): one 'SWEET HID: event size=...'
   line per second with the serialized size + the senderID (the value
   IOHIDEventSystem uses to correlate a touch to its service).

The decodes (next pratouchreset=1 boot): head advancing = drained (the
T15 conclusion, now with the rate); head stuck = the events sit; notify
armed never prints = backboardd mapped but never armed the wake-up
(the mach-message rung); event size wrong or sender=0 = the payload
correlation rung.

Marker asserted in CI (direct yml commit): 'SWEET HID: queue notify'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(diffs) + "\n")
print(f"[emit] wrote {OUT}")
for line in log:
    print("  " + line)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0192")
for rel, _new_lines in changed:
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
print("[verify] applied == expected (all files)")

# structural assertions
hdrscan = "\n".join(changed[0][1])
qcscan = "\n".join(changed[1][1])
usc = "\n".join(changed[2][1])
uchdr = "\n".join(changed[3][1])
shscan = "\n".join(changed[4][1])
assert hdrscan.count("getHead") == 1 and hdrscan.count("getTail") == 1, \
    "accessors declared once each"
assert qcscan.count("IOHIDEventServiceQueue::getHead") == 1 and \
    qcscan.count("IOHIDEventServiceQueue::getTail") == 1, "accessors defined"
assert usc.count("SWEET HID: queue notify armed") == 1, "notify line once"
assert usc.count("head=%u tail=%u") == 1, "head/tail in the stats line"
assert uchdr.count("_notifyAnnounced") == 1, "notify member in the header"
assert shscan.count("SWEET HID: event size=") == 1, "event line once"
assert shscan.count("getRegistryEntryID") >= 2, "sender present"
assert usc.count("{") == usc.count("}"), "brace balance (UC)"
assert hdrscan.count("{") == hdrscan.count("}"), "brace balance (queue h)"
assert qcscan.count("{") == qcscan.count("}"), "brace balance (queue cpp)"
assert uchdr.count("{") == uchdr.count("}"), "brace balance (UC h)"
assert shscan.count("{") == shscan.count("}"), "brace balance (SweetHID)"
print("[verify] structural assertions PASS (head/tail, notify armed, "
      "event size, per-instance notify, braces)")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0192 applies to the post-0191 delivery files")
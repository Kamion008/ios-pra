# Evidence 1 - boot T14, the touch burst (work/ring55-full.txt, own region [0, 156344))
```
PRA touch: i2c ffd73000 COMP_VERSION=3132302a COMP_TYPE=44570140
PRA touch: irq gpio28.0 dat=0 dir=0 idle=0
...
PRA touch: app mode confirmed, input reg 0x3 max_input=254
PRA touch: probe done, 10 ms poll worker started
[+ 30 s] root device ready
BSD root: sdhcroot0, major 1, minor 0
PRA touch: input poll every 10 ms (the INT line is stuck LOW)
...
PRA touch: irq lo/hi=1000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
PRA touch: irq lo/hi=2000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
PRA touch: irq lo/hi=41522/0 idle=0 reports=1 errs=0 corrupt=0 last: slot=0 x=24 y=1867 p=112
PRA touch: irq lo/hi=42522/0 idle=0 reports=2 errs=1 corrupt=0 last: slot=0 x=24 y=1867 p=112
PRA touch: irq lo/hi=59116/0 idle=0 reports=3 errs=1 corrupt=0 last: slot=0 x=534 y=1892 p=121
PRA touch: irq lo/hi=60116/0 idle=0 reports=125 errs=10 corrupt=0 last: slot=1 x=950 y=1861 p=161
...
SWEET HID: touch 0 down at 557,1378
SWEET HID: touch 0 up at 557,1378
SWEET HID: touch 0 down at 991,1158
SWEET HID: touch 1 down at 103,101
...
SWEET HID: touch 0 up at 731,548 edge
SWEET HID: touch 1 down at 993,1153
SWEET HID: touch 0 down at 502,1858
SWEET HID: touch 1 up at 993,1153
```
The burst: 60116-59116 = 1000 ticks = 10.0 s; reports 3 -> 125 = +122
=> 12.2 reports/s (python3: 122/10.0). The pad histogram is LOW for every
sample (hi=0), errs +9 in the burst window (7.4% of the 122). The tail
(ticks 61500/62500, reports 38/42) is T13's byte-identical residue in the
circular ring - excluded by the byte-diff (ring55 vs ring54 diverges at
1720; NUL run [156344, 156672); T13 residue resumes at 156672).

# Evidence 2 - the delivery path (SweetHID.cpp, the post-0190 source)
```c
IOHIDEventService::open:      IOLog("SWEET HID: %s open by %s -> %d\n", ...)
IOHIDEventService::dispatchEvent(IOHIDEvent *event, IOOptionBits options)
{
	event->setSenderID(getRegistryEntryID());
	...
	for each client:  (*data->action)(data->client, this, data->context, event, options);
}
newUserClient: type != kIOHIDEventServiceUserClientType -> super::newUserClient
SweetHIDTouch::touch:  ... dispatchEvent(collection);
```
T14: `SWEET HID: SweetHIDTouch open by IOHIDEventServiceUserClient -> 1`
and `SweetHIDButtons open by IOHIDEventServiceUserClient -> 1` (lines
960/975) - backboardd OPENED the service (kIOHIDEventServiceUserClientOpen
method). The dispatch started; nothing proves it reached the queue.

# Evidence 3 - the user client + queue internals (IOHIDEventServiceUserClient.cpp / .h, IOHIDEventServiceQueue.h)
```c
#define kQueueSizeMax   16384
static kIOHIDEventServiceUserClientOpen = 0; kIOHIDEventServiceUserClientClose = 1;
kIOHIDEventServiceUserClientCopyEvent = 2; kIOHIDEventServiceUserClientSetElementValue = 3;
kIOHIDEventServiceUserClientCopyMatchingEvent = 4;

IOHIDEventServiceUserClient::start:  _queue = IOHIDEventServiceQueue::withCapacity(this, queueSize, qOptions);
IOHIDEventServiceUserClient::eventServiceCallback:
	if (!_queue || _state != kUserClientStateOpen) return;
	_commandGate->runAction(...enqueueEventGated);
IOHIDEventServiceUserClient::enqueueEventGated:
	if (_queue) {
		++_eventCount;
		_lastEventTime = mach_continuous_time();
		_lastEventType = event->getType();
		Boolean result = _queue->enqueueEvent(event);
		if (result == false) { _lastDroppedEventTime = _lastEventTime; ++_droppedEventCount; ... }
	}
IOHIDEventServiceUserClient::clientMemoryForTypeGated:
	if (_queue) { IOMemoryDescriptor * memoryToShare = _queue->getMemoryDescriptor();
		if (memoryToShare) { ... memoryToShare->retain(); ret = kIOReturnSuccess; } }
```
```c
class IOHIDEventServiceQueue : public IOSharedDataQueue
{
	...
	inline OSObject *getOwner() { return _owner; }
	virtual Boolean enqueueEvent(IOHIDEvent * event);
	...
};
```
```c
/* the struct shared with userland */
typedef struct _IODataQueueMemory {
	UInt32            queueSize;
	volatile UInt32   head;
	volatile UInt32   tail;
	IODataQueueEntry  queue[1];
} IODataQueueMemory;
```
The header members (the quiet counters):
```c
	uint32_t                    _lastEventType;
	uint32_t                    _droppedEventCount;
	uint64_t                    _lastDroppedEventTime;
	uint64_t                    _eventCount;
```
`copyEvent` in SweetHID.cpp returns NULL - the shared queue is the ONLY
delivery path. `_eventCount`/`_droppedEventCount` were exposed only via
the never-polled DebugState serializer (serializeDebugState).

# Evidence 4 - the timebase (the review's refutation, VERIFIED)
`tools/mkadt_pra.py:32`: `TIMEBASE = 1920000  # dmesg: "Architected
cp15 timer(s) running at 1.92MHz"`, published as cpu0
'timebase-frequency'. `xnu-src/osfmk/arm/rtclock.c:166`:
mach_absolute_time() returns ml_get_timebase() = raw timebase TICKS, not
nanoseconds. So 10 s = 19,200,000 ticks and 1 s = 1,920,000 ticks. The
first 0191 draft used 10e9/1e9 (= 5208 s / 520 s = 86.8 min / 8.68 min)
- REFUTED by the deepseek review (the same unit question for
mach_continuous_time, which uses the same timebase).

# Evidence 5 - the emitted patch (xnu/patches/0191-pra-hid-queue-telemetry.patch)
```diff
--- a/iokit/Kernel/arm/hid/IOHIDEventServiceQueue.cpp
@@ -33,6 +33,7 @@
 #include "IOHIDDebug.h"
 #include <os/overflow.h>
 #include <pexpert/pexpert.h>
+extern "C" uint64_t mach_absolute_time(void);
@@ -95,6 +96,7 @@
     bool                queueFull = false;
+    static uint64_t last_drop_log;	/* 0191: at most one full-drop line per 10 s of timebase ticks (log budget) */
     bool                result    = true;
@@ -214,7 +216,15 @@
             else {
-                HIDLogError("IOHIDEventServiceQueue::enqueueEvent - Queue is full! %p", _owner);
+                if (last_drop_log == 0 ||
+                    mach_absolute_time() - last_drop_log > 19200000ull) {
+                    last_drop_log = mach_absolute_time();
+                    printf("SWEET HID: queue full drop head=%u tail=%u size=%u (%s)\n", dataQueue->head, dataQueue->tail,
+                        getQueueSize(), _owner ? ((IOHIDEventService *)_owner)->getName() : "?");
+                }
+                if (_options & kIOHIDEventServiceQueueOptionNoFullNotification) {
+                    HIDLogError("IOHIDEventServiceQueue::enqueueEvent - Queue is full! %p", _owner);
+                }
             }
```
```diff
--- a/iokit/Kernel/arm/hid/IOHIDEventServiceUserClient.cpp
@@ -174,6 +174,11 @@
         if (memoryToShare)
         {
+            if (!_mappedAnnounced) {
+                _mappedAnnounced = true;
+                printf("SWEET HID: queue mapped by %s\n",
+                    getService() ? getService()->getName() : "?");
+            }
             // Memory will be released by user client
@@ -627,6 +632,12 @@
 {
   //enqueue the event
+    uint64_t now = mach_continuous_time();
+    if (_lastStatsPrint == 0 || now - _lastStatsPrint >= 1920000ull) {
+        _lastStatsPrint = now;
+        printf("SWEET HID: queue stats enq=%llu drop=%u type=%u\n",
+            _eventCount, _droppedEventCount, _lastEventType);
+    }
     if (_queue) {
```
```diff
--- a/iokit/Kernel/arm/hid/IOHIDEventServiceUserClient.h
@@ -65,6 +65,8 @@
     uint32_t                    _droppedEventCount;
     uint64_t                    _lastDroppedEventTime;
     uint64_t                    _eventCount;
+    uint64_t                 _lastStatsPrint;	/* 0191: 1 s stats gate */
+    bool                     _mappedAnnounced;	/* 0191: map line once */
     mach_port_t                 _queuePort;
```

# Evidence 6 - the generator verify (work/gen0191.py run)
```
[emit] wrote .../xnu/patches/0191-pra-hid-queue-telemetry.patch
  [1] queue-full branch located (HIDLogError)
  [2] per-window static declared after the entry decls
  [2b] extern mach_absolute_time after the pexpert include
  [3] drop printf + HIDLogError: both still under the original else
      (NoFullNotification-branch HIDLogError preserved), drop gated to
      one per 10 s
  [4] 1 s stats line (per-instance _lastStatsPrint, enq/drop/type)
  [5] mapped-once line after a successful map (per-instance
      _mappedAnnounced)
  [6] per-instance _lastStatsPrint/_mappedAnnounced in the header
[verify] git apply --check rc=0
[verify] GNU patch --fuzz=0 --dry-run rc=0
[verify] git apply rc=0
[verify] applied == expected (both files)
[verify] structural assertions PASS (drop gate, 1 s stats, mapped-once,
      per-instance gates, braces)
[done] VERIFY PASS: 0191 applies to the post-0190 SweetHID delivery files
```
The base: work/ci191/pre0191/xnu = the SweetHID delivery files at their
post-0190 state (xnu-src, byte-identical to work/ci182/post0181).
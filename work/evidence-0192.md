# Evidence 1 - boot T15, the queue drain proof (work/ring56.raw sha e53a6455)
```
SWEET HID: SweetHIDTouch open by IOHIDEventServiceUserClient -> 1
SWEET HID: queue mapped by SweetHIDTouch
SWEET HID: SweetHIDButtons open by IOHIDEventServiceUserClient -> 1
SWEET HID: queue mapped by SweetHIDButtons
SWEET HID: touch 0 down at 524,1868
SWEET HID: queue stats enq=0 drop=0 type=0
SWEET HID: queue stats enq=67 drop=0 type=11
SWEET HID: touch 0 up at 458,149
SWEET HID: touch 0 down at 520,1919 edge
SWEET HID: queue stats enq=88 drop=0 type=11
SWEET HID: queue stats enq=157 drop=0 type=11
SWEET HID: queue stats enq=192 drop=0 type=11
SWEET HID: queue stats enq=260 drop=0 type=11
SWEET HID: queue stats enq=261 drop=0 type=11
SWEET HID: queue stats enq=263 drop=0 type=11
SWEET HID: queue stats enq=267 drop=0 type=11
SWEET HID: queue stats enq=271 drop=0 type=11
```
The burst: 54706-53706 = 1000 ticks = 10.0 s; reports 1->268 = +267
=> 26.7 reports/s (python3: 267/10.0). enq=271 with drop=0 throughout.
Drain proof: 271 events x ~304 B (the touch collection, per-event byte
count INFERRED from the struct sizes: 28 B IODataQueueEntry header + the
digitizer collection + 2 children) = ~80.5 KiB, which would overflow the
16 KiB queue ~5x if never drained (python3: 80.5/16 = 5.03) - yet
drop=0, so userland IS draining.

# Evidence 2 - the AKS sel-8 exonerated (ring56, python3 offsets)
All SpringBoard AKS calls (sel 0/7/17/26/27/32/35/8) sit at bytes
67,051-139,224. The first touch (hid inject) is at byte 143,607.
SpringBoard AKS calls AFTER the burst start: 0.
- sel 26/27 = kAKSAssertHold/kAKSAssertDrop (SweetKeyStore.cpp enum),
  return 0x0 (success) - keybag hold/drop, unrelated to touch.
- sel 8 = not in the enum -> the default case -> kIOReturnUnsupported
  (0xe00002c7) - SpringBoard calls an unknown selector at boot; it is
  BACKGROUND churn, not touch-related.
- sel 17 = kAKSGetDeviceState (0x0), sel 35 = kAKSGetExtDeviceState,
  sel 32 = unknown (0xe00002c7) - all before the burst.

# Evidence 3 - the notification arming (the unobserved link)
IOHIDEventServiceUserClient::registerNotificationPort(port, type, refCon)
  -> _commandGate->runAction(registerNotificationPortGated)
registerNotificationPortGated: _queuePort = port; _queue->setNotificationPort(port)
IOHIDEventServiceQueue::setNotificationPort: super::setNotificationPort(port);
  if (dataQueue->head != dataQueue->tail) sendDataAvailableNotification();
sendDataAvailableNotification: _notificationCount++; super::sendDataAvailableNotification()
The mach message wakes backboardd when data lands. Whether backboardd
calls registerNotificationPort at all is NOT currently logged anywhere.

# Evidence 4 - the queue head/tail semantics
IOHIDEventServiceQueue::enqueueEvent:
  tail = atomic_load(&dataQueue->tail)    // the producer (kernel) tail
  head = atomic_load(&dataQueue->head)    // advanced by the CONSUMER (userland)
The IODataQueueMemory struct (IODataQueueShared.h): queueSize, volatile
head, volatile tail, queue[1]. The producer (kernel enqueue) advances
TAIL; the consumer (userland dequeue) advances HEAD. So head advancing
= userland is actually dequeuing.

# Evidence 5 - the patch (xnu/patches/0192-pra-hid-drain-telemetry.patch)
```diff
--- a/iokit/Kernel/arm/hid/IOHIDEventServiceQueue.h
@@ -40,6 +40,9 @@
      inline void setState(Boolean state) { _state = state; }
      
      inline OSObject *getOwner() { return _owner; }
+    /* 0192: the queue head/tail - head advances as userland dequeues. */
+    inline UInt32 getHead() { return dataQueue ? dataQueue->head : 0; }
+    inline UInt32 getTail() { return dataQueue ? dataQueue->tail : 0; }
  
      virtual Boolean enqueueEvent(IOHIDEvent * event);
--- a/iokit/Kernel/arm/hid/IOHIDEventServiceUserClient.cpp
@@ -133,6 +133,12 @@
      _queuePort = port;
      
      if (_queue) {
+        static bool notify_announced;	/* 0192: once */
+        if (!notify_announced) {
+            notify_announced = true;
+            printf("SWEET HID: queue notify armed by %s\n",
+                getService() ? getService()->getName() : "?");
+        }
          _queue->setNotificationPort(port);
      }
@@ -635,8 +641,9 @@
      uint64_t now = mach_continuous_time();
      if (_lastStatsPrint == 0 || now - _lastStatsPrint >= 1920000ull) {
          _lastStatsPrint = now;
-        printf("SWEET HID: queue stats enq=%llu drop=%u type=%u\n",
-            _eventCount, _droppedEventCount, _lastEventType);
+        printf("SWEET HID: queue stats enq=%llu drop=%u type=%u head=%u tail=%u\n",
+            _eventCount, _droppedEventCount, _lastEventType,
+            _queue ? _queue->getHead() : 0, _queue ? _queue->getTail() : 0);
      }
      if (_queue) {
--- a/iokit/Kernel/arm/hid/SweetHID.cpp
@@ -213,6 +213,13 @@
  	clients->retain();
  	IOLockUnlock(_clientLock);
  
+	static uint64_t last_evlog;	/* 0192: 1 s cadence */
+	uint64_t evnow = mach_absolute_time();
+	if (last_evlog == 0 || evnow - last_evlog >= 1920000ull) {
+		last_evlog = evnow;
+		printf("SWEET HID: event size=%u sender=0x%llx\n",
+		    (unsigned)event->getLength(), getRegistryEntryID());
+	}
  	for (unsigned int i = 0; i < clients->getCount(); i++) {
```

# Evidence 6 - the generator verify (work/gen0192.py run)
```
[emit] wrote .../xnu/patches/0192-pra-hid-drain-telemetry.patch
  [1] getHead/getTail accessors in IOHIDEventServiceQueue.h
  [2] stats line extended with head/tail (the drain rate)
  [3] notify-armed line in registerNotificationPortGated
  [4] event size + sender line (1 s cadence) in dispatchEvent
[verify] git apply --check rc=0
[verify] GNU patch --fuzz=0 --dry-run rc=0
[verify] git apply rc=0
[verify] applied == expected (all files)
[verify] structural assertions PASS (head/tail, notify armed, event size, braces)
[done] VERIFY PASS: 0192 applies to the post-0191 delivery files
```
The base: work/ci192/pre0192 = work/ci191/pre0191 (the post-0190 files)
+ the 0191 patch applied cleanly (git apply, all 3 files).
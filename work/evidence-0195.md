# Evidence 1 - T18/ring59 is a zero-report boot (work/ring59-own.txt)

The T18 boot line (work/ring59-own.txt, 2,104 lines) carries the exact cmdline:
```
boot-args = ... pratouch=1 pratouchreset=1
```
Probe and worker:
```
PRA touch: HID desc len=32 bcd=0x100 ... vid=0x4b4 pid=0xc101 ver=0x100 (err=0)
PRA touch: app mode confirmed, input reg 0x3 max_input=254
PRA touch: probe done, 10 ms poll worker started
PRA touch: input poll every 10 ms (the INT line is stuck LOW)
```
The only telemetry samples:
```
PRA touch: irq lo/hi=1000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
PRA touch: irq lo/hi=2000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
```
Counts (Python, exact substrings):
```
   0  SWEET HID: touch
   0  PRA touch: hid inject
   2  PRA touch: irq lo/hi
   2  reports=0
   1  app mode confirmed
```
`pra_live` is true (the app-mode line only prints when input_reg != 0), so
the worker was in the read path. There is no `SWEET HID: touch` line at all,
so 0194's clamp was never called. The boot reached SpringBoard: ring59 has
`SWEET AKS: SpringBoard ...` lines and the `boot marks` summary says
backboardd/SpringBoard yes.

# Evidence 2 - the T18 image contains 0194

The boot image's kernel field is a gzip payload. Decompressing it and
searching the 0194 marker:
```
contains SWEET HID: panel arm A5XELTE 1080x1920 True
contains SWEET HID: touch registered True
contains SWEET HID: surface True
```
The CI kernel disassembly (`work/ci194/dl/kernel.development.pra`, sha256
b23cdd20bcdfd79d3868c18de8b39bcfb9b47bbc9c571e5002594c55a147862b):
```
fffffff007a5c2dc: ldr  d0, [x8, #0x630]
fffffff007a5c2e0: ldr  q1, [x9, #0x700]
fffffff007a5c2e4: str  d0, [x19, #0xc0]      ; fPanelW/fPanelH
fffffff007a5c2e8: str  q1, [x19, #0xb0]      ; fLogicalW/H, fOffX/Y
fffffff007a5c2ec: bl   _IOLog                 ; "panel arm A5XELTE ..."
```
The const bytes at 0xfffffff00702e630 are `38 04 00 00 80 07 00 00`,
i.e. (1080, 1920). `touch()` at 0xfffffff007a5c428 loads
`[x19,#0xc0]`, subtracts 1, and csel-selects it only when the panel is
larger than x; same for `[x19,#0xc4]`. This is the 0194 code in the
flashed image. Runtime execution is still unproven because T18 produced no
`touch()` call.

# Evidence 3 - the 0195 patch

pra_touch.c heartbeat (patch lines 36-70):
```
+ uint32_t reads_total = 0, last_len = 0;
...
+ reads_total++;
+ last_len = len;
...
+ if (loops - last_print >= loops_per_10s &&
+     (pra_touch_dbg || (evt_total != evt_mark) || ...
...
+ "errs=%u corrupt=%u reads=%u last_len=%u "
```
The source of `last_len` semantics (pra_touch.c:870-878):
```
size = pra_touch_le16(lenb);
if (size == 0 || size == 2) {
    *lenp = 0;              /* nothing pending */
    return 0;
}
```
So `last_len=0` is "nothing pending", not a raw 2.

SweetHID.cpp selftest (patch lines 102-121):
```
+extern "C" void
+sweet_hid_touch_selftest(IOHIDEventService *svc)
+{
+    if (!gSweetTouch || svc != gSweetTouch || !gSweetTouchSelfTest) {
+        return;
+    }
+    gSweetTouchSelfTest = false;
+    IOLog("SWEET HID: selftest raw 2000,3000\n");
+    gSweetTouch->touch(0, true, 2000, 3000);
+    gSweetTouch->touch(0, false, 2000, 3000);
+}
```
The raw point is out of bounds by design. 0194's clamp is
`x >= fPanelW ? fPanelW - 1 : x` (same for y); with fPanelW/H = 1080/1920
the touch() lines must print 1079,1919. An in-bounds 550,1911 would not
invoke the clamp and would not distinguish a broken clamp with set dims.
and the boot-arg arm in start():
```
+ uint32_t selftest = 0;
+ if (PE_parse_boot_argn("pratouchselftest", &selftest, sizeof(selftest)) &&
+     selftest) {
+     gSweetTouchSelfTest = true;
+     IOLog("SWEET HID: selftest armed\n");
+ }
```
User-client map hook (patch lines 127-141):
```
+extern "C" void sweet_hid_touch_selftest(IOHIDEventService *svc);
...
+ if (result == kIOReturnSuccess && _state == kUserClientStateOpen) {
+     sweet_hid_touch_selftest(_owner);
+ }
```
`clientMemoryForType` is the function that prints `SWEET HID: queue
mapped by ...` in the T18 ring, so this hook is on the observed map path.
The call is after the command gate returns and after `_state` is open; the
callee ignores the SweetHIDButtons map by comparing `_owner` with
`gSweetTouch`.

# Evidence 4 - generator three-way verify

```
$ python3 work/gen0195.py
[emit] wrote .../0195-pra-touch-selftest.patch
[verify] git apply --check rc=0
[verify] GNU patch --fuzz=0 --dry-run rc=0
[verify] git apply rc=0
[verify] bsd/dev/pra_touch.c: applied == expected
[verify] iokit/Kernel/arm/hid/SweetHID.cpp: applied == expected
[verify] iokit/Kernel/arm/hid/IOHIDEventServiceUserClient.cpp: applied == expected
[verify] structural assertions PASS (heartbeat, selftest, map hook)
[done] VERIFY PASS: 0195 applies to post-0194 pra_touch.c + SweetHID.cpp + post-0192 user client
```
The base reconstruction: 0190 applied to post0189 pra_touch.c; 0193 and
0194 applied to pre0193 SweetHID.cpp; the user client is the pre0193
(post-0191/0192) file. The generator asserts the base contains
`SWEET HID: queue stats` and `SWEET HID: queue notify` before editing.

# Evidence 5 - cmdline arithmetic

Python:
```
base len 451
add len 33
total len 484
under 512: True
```
The T19 cmdline is the T18 451-byte cmdline plus ` pratouchdbg=1
pratouchselftest=1`; 484 bytes, below the 512-byte boot-arg field.

# Evidence 6 - T17 contrast (the 0194 target)

ring58's pair:
```
PRA touch: hid inject slot=0 down x=550 y=1911
SWEET HID: touch 0 down at -1,-1 edge
```
0194 initialized fPanelW/H in the compiled arm; the T18 image contains
that code. T19's out-of-bounds selftest (raw 2000,3000) is the first
measurement that forces the running clamp; expected 1079,1919.

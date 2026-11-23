# 0202 DESIGN PREP — publish the host-state contract (DRAFT, pending ring65)

STATUS: PREP ONLY. Do NOT write/commit/CI the patch until ring65 (T22) confirms
the push — the handoff fork: no `setElementValue`/`setProperties` line in the whole
boot → 0202 is the wrong lever, do the tracev3 route-log decode instead
(digitizer-gate-2026-11-22.md §5). Written 2026-11-23 while T22 boots unattended.

BASES (VERIFIED, corrected — see claim-0201 K3):
- work/0202/SweetHID-pre0202.cpp == CI tree post-0201 (cmp rc=0 vs
  /tmp/opencode/ci-tree-0201/src/xnu/iokit/Kernel/arm/hid/SweetHID.cpp, 875 lines).
- work/0202/SweetFramebuffer-pre0202.cpp == CI tree post-0201 INCLUDING 0171's
  prague_gpu block. DO NOT use work/0201/SweetFramebuffer-*0201.cpp — that
  derivation missed the GPU block (the 0201 header's claim was wrong; the patch
  itself landed fine, contexts don't overlap).
- Round-trip proven: bases -R 0201 + 0201 == bases, fuzz=0, cmp rc=0 (both files).
- Push path confirmed: IOHIDEventServiceUserClient.cpp:75-76 (external method
  table) → :507-513 _setElementValue → target->setElementValue(page, usage, value).

THE FOUR ITEMS (handoff + digitizer-gate §4 0202), with post-0201 line anchors:

1. MultitouchHostStateKeys — SweetHIDTouch::start(), after the DisplayIntegrated/
   SurfaceWidth/SurfaceHeight properties (base :656-658). Publish an OSArray of
   OSString with exactly the keys we honour: ScreenOn, DigitizerSurfaceCovered,
   PocketTouchesExpected. WakeOnTapEnabled ONLY together with 0203's tap-to-wake
   delivery, never before (advertising it without the path is a lie backboardd
   will act on). OSArray/OSString already used in this file; no new includes.
   Semantics honesty: this port has NO proximity/ALS sensor service (VERIFIED
   absence, digitizer-gate §1a) — DigitizerSurfaceCovered/PocketTouchesExpected
   are accepted-and-stored with default NO, not sensed. ScreenOn maps to the
   framebuffer power state once 0203 makes it honest; until then store only.

2. setElementValue accept — IOHIDEventService::setElementValue (base :245-260).
   Accept the host-state usages, store them, log transitions, return
   kIOReturnSuccess; keep kIOReturnUnsupported (and the 0201 log line) for
   everything else. OPEN — ring65 must name the exact (usagePage, usage) pairs:
   the kernel's IOHIDUsageTables.h ends at the public digitizer usages
   (0x55 ContactCountMaximum); the host-state usages are Apple-private and the
   0201 log prints them raw. Storage sketch: a small fixed table on
   IOHIDEventService (protected), e.g. { page, usage, value, set } x N, matched
   linearly (a few writes per boot, not a hot path); log old->new on change.
   Which service receives the push: the 0201 line's %s getName() tells us
   (SweetHIDTouch vs SweetHIDButtons) — gate acceptance on the digitizer service
   if only it is pushed to (host state is a digitizer concept; the base class is
   shared with the buttons service).

3. Will/DidUpdateMask — SweetHIDTouch::touch() (base :687-788). backboardd's
   check (VERIFIED string @0xcd925 in the T21-era binary): "ignoring subevent
   with nonzero didUpdateMask (on parent event with zero didUpdateMask)". So the
   COLLECTION's didUpdateMask must be nonzero whenever any child's is. Set
   kIOHIDEventFieldDigitizerWillUpdateMask and ...DidUpdateMask on each child
   from the fields actually written (X, Y, Touch, Range, EventMask, Identity,
   Index, IsDisplayIntegrated — bits kIOHIDDigitizerEventUpdate*Mask,
   IOHIDEventTypes.h:577-605, 1<<IOHIDEventFieldOffsetOf(field)), and on the
   collection from its own fields (X, Y, Range, Touch, EventMask, ButtonMask,
   Collection, IsDisplayIntegrated) OR the union of child update bits. Both
   masks set to the same computed value is honest here: the fields are written
   synchronously in this call. 0201 already sets IsDisplayIntegrated on
   collection+children (base :727, :763) — keep it, add its update bit.

4. SurfaceDimensions — SweetHIDTouch::start(), next to the two raw numbers
   (base :656-658). OSDictionary{ kIOHIDWidthKey: OSNumber(68<<16, 32),
   kIOHIDHeightKey: OSNumber(121<<16, 32) } under kIOHIDSurfaceDimensionsKey
   (IOHIDEventServiceKeys.h:110/120/130; IOFixed millimetres 16.16). Values from
   the A5XELTE arm (68x121 mm) — the arm that compiles on PRA (both board macros
   defined; 0194 lesson). Do NOT publish a pixel rect anywhere
   (normalizedDigitizerRect {{0,0},{1,1}} is correct, REFUTED suspect, E4).

MARKER DISCIPLINE (the 0201 lesson, claim-0201 K5): assert on contiguous
substrings of the new format literals, verified with `strings -a` on the BUILT
kernel before writing the workflow assert. Candidates:
- 'SWEET HID: hoststate keys published' (whole literal, no %s inside) — item 1/4.
- 'usage 0x%x value 0x%x -> accepted' (contiguous tail of the accept format;
  the %s name sits BEFORE it, exactly the 0201 trap) — item 2.
- 'SWEET HID: digitizer update masks set' (once per boot, static flag like
  0201's dispIntegLogged) — item 3.

THREE-WAY VERIFY (0164 method, AGENTS.md): stage scripts + `git apply` of the
FULL stack in a scratch tree (zero skips), GNU `patch -p1 --fuzz=0 --dry-run` on
the index-stripped 0202 diff against the bases, real apply + byte cmp against
the derived post files; plus the claim-0198 skip-detection re-run (already-applied
tree must give rc=1 for both tools). CI: push master, RUNNER=macos-15 dispatch,
cancel the push-triggered A5XELTE run, check the asserts in the run log — a green
CI without checked asserts proves nothing.

WHAT RING65 MUST ANSWER BEFORE THE PATCH IS WRITTEN:
1. The fork: any setElementValue/setProperties line at all? (absent → stop, §5 decode)
2. Exact (page, usage) pairs + values pushed → the accept-list (item 2).
3. Which keys arrive via setProperties → whether host state also comes as
   properties, and whether item 1's array must match them.
4. Timing: pushes at boot, at wake (adjacent to the 30 s key pairs), or both →
   whether accepting at boot suffices or transitions must be reacted to.
5. powerreq/notifyreg results → 0203 scope (keep_on drop, notify() on power
   transitions, DisplayPowerOff read-back). 0203 stays LAST — it can blank the
   panel, and only after 0202's wake path works.

RISK NOTES: accepting usages we do not honour makes backboardd believe the
digitizer is configured when it is not — keep the accept-list minimal and the
published keys honest. The keys stay ON for the 0202 test boot too (positive
control); the KEYLESS boot is the deliverable test AFTER 0202 lands, and only
then do prapowerkey/prakeyevery come off.

# CLAIM: 0202 (the digitizer host-state contract — write 0202 after ring65)

Author: session 2026-11-23 (the T22 fork result). Claim for the landed patch
`xnu/patches/0202-pra-hid-hoststate-contract.patch`. Base = work/0202/*-pre0202.*
(= the post-0201 CI build tree). Companion: work/evidence-0202.md (three-way
verify), work/0202-design.md (the pre-write design), work/boots.md T22 outcome
(the ring65 evidence that authorized this write), work/claim-0201 K4 (the fork).

K1 (VERIFIED, ring65): THE FORK RESOLVED — backboardd DOES configure through the
event service, and 0202 is the right lever. ring65 (sha 93eb49d572aec32b, pulled
from TWRP 2026-11-23 15:05:40 UTC) holds 40 `SWEET HID: %s setProperties key`
lines and ZERO `setElementValue` lines (grep counts, quoted in the T22 outcome):
TouchDetectionMode x16 (SweetHIDTouch), PreserveTimestamp x8, MotionEventRestricted
x4, GraphicsOrientation x2, ReportInterval/BatchInterval/DeviceOpenedByEventSystem/
LogLevel x2 each, QuantizationDPI/HIDSubinterfaceID x1. No host-state key
(ScreenOn/DigitizerSurfaceCovered/PocketTouchesExpected) ever arrives: backboardd's
BKHIDUIHostStateDigitizerServiceWrapper only pushes host state to services that
PUBLISH MultitouchHostStateKeys — this port published none (the contract gap the
0201 instrumentation was built to find). The handoff's stop-condition ("no
setElementValue AND no setProperties line") was NOT hit: the property channel is
exercised, the element channel is silent only because nothing was advertised.

K2 (VERIFIED, source): WHAT 0202 DOES — the four items of work/0202-design.md:
1. SweetHIDTouch::start() publishes `MultitouchHostStateKeys` = OSArray[OSString:
   ScreenOn, DigitizerSurfaceCovered, PocketTouchesExpected] — exactly the keys
   we can honour (ScreenOn stored, tied to display power only from 0203;
   the other two stored, default NO, this port has no proximity sensor).
   WakeOnTapEnabled deliberately NOT advertised (it implies a tap-to-wake path
   that does not exist before 0203 — advertising a lie backboardd would act on).
   Also publishes `SurfaceDimensions` = {Width: 68<<16, Height: 121<<16} (IOFixed
   mm 16.16, the A5XELTE arm's values — the arm that compiles on PRA, the 0194
   lesson) next to the existing raw SurfaceWidth/SurfaceHeight.
2. setElementValue (IOHIDEventService) accepts PRIVATE digitizer-page usages
   (usagePage == kHIDPage_Digitizer && usage > 0x55, beyond the public table
   this tree knows): store in the new 8-entry _hostState table, log the transition
   with old-value, return kIOReturnSuccess. Public usages / other pages keep the
   0201 refusal + log. setProperties honours the three advertised keys on the
   EXERCISED channel (K1): store as read-back property + log `keyvalue %s = %u`
   (TouchDetectionMode's values, invisible until now, logged too).
3. touch() sets Will/DidUpdateMask on every child (the fields actually written:
   X,Y,Touch,Range,EventMask,Identity,Index,IsDisplayIntegrated) and on the
   COLLECTION (its own fields | union of children) so the parent is nonzero
   whenever any child is — backboardd's VERIFIED check "ignoring subevent with
   nonzero didUpdateMask (on parent event with zero didUpdateMask)"
   (/tmp/pra-bin/backboardd @0xcd925, digitizer-gate-2026-11-22.md:163).
4. IOHIDEventService.h: the fixed 8-entry HostStateEntry table (zeroed alloc).

K3 (VERIFIED, command + work/evidence-0202.md): THREE-WAY VERIFY PASSED, zero
skips. Leg 1 GNU patch -p1 --fuzz=0 --dry-run + apply on the CI-0201 base, cmp
rc=0 both files. Leg 2 the 0164 method: pristine xnu-8796.141.3 (apple-oss,
1b191cb), stage scripts with MACHINE_CONFIG=PRA MACOS_VERSION=13.5 (0026 staged
hfs-627.100.6), then `git apply --check && git apply` over ALL 193 patches in
glob order — **skips: 0** — and the resulting SweetHID.cpp / IOHIDEventService.h
byte-match work/0202/*-post0202.* (cmp rc=0), SweetFramebuffer.cpp byte-matches
the CI-0201 tree (0202 touches no FB file). (A first run with the env unset
skipped 0031/0041 for missing bsd/sweet_hfs — superseded, recorded for honesty.)
Leg 3 already-applied discrimination: on the post-0202 tree `git apply --check`
rc=1 with "patch does not apply" AND GNU `patch -R`-detect dry-run rc=1, so the
leg-2 rc=0 is a real apply, not a skip (AGENTS.md:44-49). Hunk arithmetic: python3
exact recount, all 7 hunks consistent (the awk one-liner's `ok=0` on hunk 1 was
an awk artifact — it missed the blank context line; python3: ctx=6 add=10
-> 6/6, 16/16 OK).

K4 (VERIFIED, source): MARKERS — four contiguous format-literal tails, chosen
per the 0201 lesson (claim-0201 K5: the %s service name sits BETWEEN prefix and
verb, so assert on the TAIL): `hoststate keys published`, `-> accepted (was %u
set %d)`, `keyvalue %s = %u`, `SWEET HID: digitizer update masks set`. All four
grep -F present in the patch source (4/4) and are asserted against the BUILT
kernel in .github/workflows/xnu.yml (added this session, after the 0201 guard
block).

K5 (PREDICTION, ring66 decides): with 0202 landed and flashed WITH the keys still
on (positive control): (a) `SWEET HID: hoststate keys published (...)` once at
start(); (b) backboardd now has something to push — expect `keyvalue ScreenOn /
DigitizerSurfaceCovered / PocketTouchesExpected` lines and, if the wrapper uses
the element path, `setElementValue page 0x.. usage 0x.. -> accepted` (the
page/usage values NAME the Apple-private usages we could not recover offline —
K6); (c) `digitizer update masks set` once before first touch; (d) touch still
works via the synthetic wake as in T21c/T22 (the keys stay until the keyless
test). THE DELIVERABLE TEST is the NEXT boot after this one: same image,
WITHOUT prapowerkey/prakeyevery — touch must work from boot with no synthetic
key. Falsifiers: (b) absent entirely → backboardd ignores the advertised keys
(the handshake is something else: 0203's display-power honesty or the SpringBoard
sensor-mode assertion → tracev3 route-log decode, digitizer-gate §5); a boot
without (a) → 0202 was skipped (the CI asserts catch it before the flash).

K6 (UNKNOWN, named by design): the exact Apple-private (usagePage, usage) pairs
for ScreenOn/DigitizerSurfaceCovered/PocketTouchesExpected. The open-source
IOHIDFamily tables have no such usages (public digitizer table ends 0x55 here,
0xA1 upstream), no donor tree implements MultitouchHostStateKeys, the T21-era
backboardd binary is gone from /tmp. The accept net is bounded (page==Digitizer,
usage>0x55) precisely so ring66's `-> accepted` lines enumerate them — a bounded
guess whose falsifier (nothing arrives) is itself the evidence.

K7 (SCOPE/risk): accepting a usage we do not honour makes backboardd believe the
digitizer is configured when it is not — hence the minimal published key set,
WakeOnTapEnabled withheld, and 0203 (display power honesty, can blank the panel)
still LAST and not part of this patch. 0202 touches no framebuffer file
(evidence-0202 §2, cmp rc=0).

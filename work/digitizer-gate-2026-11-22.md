# Digitizer gate: where `digitizerEnabled` and `normalizedDigitizerRect` come from

Date: 2026-11-22. Author: research sub-agent (read-only). No code changed, no
commit, no device access, no adb. This note supersedes nothing; it narrows the
two new suspects named in `work/userland-logs-2026-11-22.md` (E3 display/digitizer
gate, E4 1x1 digitizer rect).

Labels: **VERIFIED** = I read the bytes/source at the cited anchor. **INFERRED** =
consistent with the anchors but not directly observed. **UNKNOWN** = not settled
here, with the test that would settle it.

---

## 0. Evidence base (new, read-only, host-side)

Everything in section 0 is new since `userland-logs-2026-11-22.md`; it is what
turns four of the open questions into anchors.

**The unified-log bytes were still cached on the host** (the run's scratch dir
survived):

    /tmp/pra-forensics/pull/private__var__db__diagnostics__Persist__0000000000000001.tracev3
      10,436,472 B, the same archive §5 of the log doc quotes

Offsets below are decimal byte offsets in that file (`grep -abo`, `od -c`).
I did not re-run `strings` on a stale copy: I generated
`/tmp/pra-forensics/p1-off.txt` (`strings -a -t d -n 3 <archive>`, 187,699 lines)
so every fragment has a byte offset.

**The real userland binaries were read out of the IPSW** — the device root is
build 20H392 (`com.apple.springboard.plist`, `SBLastSystemVersion = '20H392'`,
quoted in `work/userland-logs-2026-11-22.md` §6) and the IPSW on disk is
`research/ipsw-x/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw`. Read-only
extraction with 7-Zip, no mount, no write to the image:

    7z e -so <ipsw> '087-86593-047.dmg' > /tmp/dmgwork/sys.dmg          # 2,743,074,816 B
    7z e -so <ipsw> 'iOSRoot/usr/libexec/backboardd' > /tmp/pra-bin/backboardd
    7z x sys.dmg -o<dir> 'System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64*'

    /tmp/pra-bin/backboardd  sha256 7aa6f8bf5ea2c3634fb8c8916a4e9c3c84508de78eccf57ca65c1ae4f676267c
      1,184,848 B, Mach-O 64-bit arm64 (iOS 16.7.16 backboardd)

The split dyld shared cache (46 subcaches + `.dylddata`/`.dyldlinkedit`,
~2.5 GB extracted) yields `BackBoardServices` (subcache `.01` and `.05`) and
`CoreBrightness` strings. `seven zip` can read the HFSX device root too
(`research/iosroot/ios16-root-v12.img`, `Method = HFSX`), but its
`System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64*` files are
0-byte placeholders there — the IPSW cache is the only usable copy on this host.

String offsets in this note are `strings -a -t x` offsets inside
`/tmp/pra-bin/backboardd` or inside `dyld_shared_cache_arm64.05`, so they are
reproducible from the commands above.

---

## 1. `digitizerEnabled: NO` — what actually computes it

**VERIFIED: it is not computed by backboardd from our kernel object. It is a
field of a `BKSHIDUISensorMode` asserted by a userland client, and the winning
assertion is SpringBoard's.**

`dyld_shared_cache_arm64.05` @1324421 (`strings`):

    BKSHIDUISensorMode
    BKSHIDUISensorMode.m
    BKSUISensorMode cannot be subclassed
    changeSource
    displayState
    digitizerEnabled
    pocketTouchesExpected
    multitouchHostStateKeys
    …
    score
    _reason
    _versionedPID
    _changeSource
    _proximityDetectionMode
    _displayState
    _digitizerEnabled
    _pocketTouchesExpected
    _multitouchHostStateKeys

That property set matches, field for field, the record quoted as E3 and its
siblings in the archive. Re-extracted with more context (byte offsets in the
tracev3):

| tracev3 offset | recovered record (fragments) |
|---|---|
| 2625921 | `<score: 4108; vpid: 26(v45); [SpringBoard]; reason: SB + boot; … digitizerEnabled: NO; … multitouchHostStateKeys: (WakeOnTap…)>` (preceded at 2625500 by `<SBHIDUISensorMode…: 0x…19bf280; suspendProximity: YES; pocketTouchesExpect…; digitizer: tapToWake; display: <unspecified…>`) |
| 3920838 | `<score: 4108; vpid: 26(v45); Spring…SB + backlight-off + pocketTouches; proximityDetectionMode: l…; digitizerEnabled: NO; display: off; multitouchHostStateKeys: (WakeOnTap…)>` |
| 4106514 | same score-4108 record (the one quoted as E3) |
| 4465801 | `<score: 1; vpid: 56(vD2); backboardd; reason: baseline + pocketTouchesEnabled(SB…); … digitalizerW…k: YES; … display: on` (backboardd's own baseline mode, score 1) |
| 5243756 | `<score: 4108; vpid: 26(v45); …SB + …; …Enabled … multitouchHostStateKeys: (…OnTap…)>` |
| 6358867 | `<score: 4108; vpid: 26(v45); …; reason: SB + pocketTouches + backlight-off; proximityDetectionMode: …; digitizerEnabled: NO; displayState: …; multitouchHostStateKeys: (WakeOnTap…)>` |

Two consequences, both load-bearing:

1. **`score` is a mode-priority number, not a brightness.** SpringBoard's mode
   scores 4108, backboardd's baseline scores 1, so SpringBoard's
   `digitizerEnabled`/`displayState` is the value that wins. `python3`:
   `4108 = 0x100c`, a plain integer — do not read it as a percentage or a
   brightness.
2. **`display: off` in E3 is `displayState: off`** — at 6358867 the fragment is
   `displayState:` (`…display` + `State:` split by the OSLog encoder, exactly
   like `norm`+`edDigitizerRect`). So E3's two fields are
   `digitizerEnabled` and `displayState`, i.e. *the same object's* mode, not two
   independent observations.

**VERIFIED: the blank that produced `displayState: off` came from the idle
timer, not from the framebuffer.** Byte dump at tracev3 6354250:

    …0x143d06500 t…to displayMode:Off dur…:0.185000 seqId:3 interrupting
    previous se… … 1 with started at:16:42:51.406 … backlight … te for
    event:<BLSB…ChangeE…262100; id: 2;> … e: Off; … State: ActiveOn; request: \
    …edL…qOff/Ina…; explanation: "idle timer"; stamp: 5053946308; source: Idle…

`explanation: "idle timer"` (**VERIFIED** string); "BacklightServices blanked the
display because nothing reset the idle timer" is **INFERRED** (that string is
inside a BLS transition record, and BLS is the blanking authority backboardd
observes: `display:didBecomeBlank:` @0xb8063, `display:didBlank:` @0xb807b,
`BKDisplaySetDisplayBlanked` @0xc17d6, `%@ - blanking display: %@` @0xc820b in
backboardd).

So the causal chain that the evidence supports is:

    no accepted touch → idle timer → BLS displayMode:Off → SpringBoard asserts
    BKSHIDUISensorMode(displayState: off, digitizerEnabled: NO,
    multitouchHostStateKeys: (WakeOnTap…)) with score 4108 → backboardd applies it

i.e. **`digitizerEnabled: NO` is the *normal sleep* mode of a healthy device,
not by itself proof of a fault.** It is a state gate on delivery, and the only
way it hurts us is if it is latched while the user is tapping — the taps then
have to arrive through the tap-to-wake path instead of the normal touch path.
The archive contains the complementary record (score 1, backboardd,
`display: on`, `…W…k: YES`) as well, so both states existed during the boot; the
archive does not date either one to a press.

### 1a. Which of the candidate causes our port can influence

| cause | can the kernel influence it? | anchor |
|---|---|---|
| display/backlight blanking (`displayState: off`) | **partly.** Only through what CoreBrightness/BacklightServices can observe from the display driver: the power-request reply, a brightness interface, blank/unblank notifications. | tree: no brightness selector exists, unknown selectors return zeros — `xnu-src/iokit/Kernel/arm/SweetFramebuffer.cpp:57-66` (selector enum ends at 72 Notifications), `:647-652` (scalar output zero-filled, structure output bzero'd, `ret` stays `kIOReturnSuccess` for every unimplemented selector) |
| `backlight-off` reason inside the mode | **partly, same lever** — it is a CB reason string (`" + pocketTouchesEnabled(%@)"` @`.05`+1324849 region is the sibling reason builder), fed by CB's own bookkeeping | **INFERRED** |
| pocket / proximity (`pocketTouchesExpected`, `suspendProximity`) | **no.** There is no proximity or ALS HID service in this port at all (grep: the only HID event services in the port are `SweetHIDButtons` and `SweetHIDTouch`, `work/0200/SweetHID-post0200.cpp:335, 410`, registered from `start()` at `:97-98`) | **VERIFIED** absence; the sensor-mode records show both `pocketTouchesExpected: NO` and a pocket-flavoured reason, so a missing sensor does not veto the mode by itself |
| lock / idle timer | **no** — SpringBoard internal | **VERIFIED** (BLS record above) |
| tap-to-wake path (`multitouchHostStateKeys: (WakeOnTap…)`) | **yes, and this is the part the tree provably fails** — see 1b | **VERIFIED** |

### 1b. The interface our kernel has to satisfy, and where the tree fails it

Backboardd's host-state machinery (**VERIFIED** strings in `/tmp/pra-bin/backboardd`):

    d04df  BKHIDUIHostStateDigitizerServiceWrapper
    bcb6e  setElementValue:forUsagePage:usage:
    b30c1  _queue_applyCachedPropertiesToMultitouchService:
    ba528  multitouchHostStateKeys        (setter bd5e4 setMultitouchHostStateKeys:)
    c389d  NeedsHostState
    c1b27  HostStateNotification
    cd7f8  send tapToWake to %{public}@ pid:%{public}@
    cda8d  received tapToWake
    cde28  digitizer:%llX - display:%{public}@ - %{public}@
    cdd4d  %llX ignoring touch event (%{public}@) prevHadTouches:%{BOOL}u nowHasTouches:%{BOOL}u
    cda39  didn't see a previous touch down or range-in event for pathIndex:%d; skipping event
    cd925  ignoring subevent with nonzero didUpdateMask (on parent event with zero didUpdateMask)

The host-state key vocabulary (**VERIFIED**, `.05` @1324849):

    WakeOnTapEnabled CoverGestureEnabled WakeOnSwipeEnabled WakeOnLongPressEnabled
    WakeOnTapThroughEnabled WakeOnSwipeThroughEnabled WakeOnLongPressThroughEnabled
    ScreenOn DigitizerSurfaceCovered PocketTouchesExpected FaceTouchesExpected

So a digitizer service is expected to (a) advertise which host-state keys it
honours via the `MultitouchHostStateKeys` property, and (b) accept host-state
writes. The port does neither:

| required | tree state | anchor |
|---|---|---|
| `MultitouchHostStateKeys` property on the service | **not published** — the only digitizer properties set are `DisplayIntegrated`, `SurfaceWidth`, `SurfaceHeight` | `work/0200/SweetHID-post0200.cpp:621-624`; grep for `Multitouch\|HostState` in `xnu-src/iokit/Kernel/arm/hid/SweetHID.cpp` returns nothing |
| accept host-state element writes (`setElementValue:forUsagePage:usage:` reaches `IOHIDEventServiceUserClient::_setElementValue` → `IOHIDEventService::setElementValue`) | **refused**: `return kIOReturnUnsupported;` | `work/0200/SweetHID-post0200.cpp:245-248`; dispatch path `xnu-src/iokit/Kernel/arm/hid/IOHIDEventServiceUserClient.cpp:72-76, 486-504` |
| accept pushed properties (`setProperties:`) | **swallowed**: returns success for any dictionary and does nothing (so it cannot even be observed) | `work/0200/SweetHID-post0200.cpp:250-255` |
| digitizer events flagged display-integrated | **never set**: the field exists (`kIOHIDEventFieldDigitizerIsDisplayIntegrated`, `IOHIDEventFieldDefs.h:161`) and the struct bit exists (`IOHIDEventStructDefs.h:334`), but no event in `touch()` sets it — only the service *property* is set | `work/0200/SweetHID-post0200.cpp:622` vs the event build at `:689-731` |
| the framebuffer tells userland it is on / off | **never**: the only notification ever sent is the vsync (`notify(SWEET_FB_NOTIFY_VSYNC…)`), on every vsync; no power/blank notification exists, and no client has ever registered one | `xnu-src/iokit/Kernel/arm/SweetFramebuffer.cpp:246-259`; rings 60-63 contain **zero** `sel 72` lines and zero `notifications type` lines (grep) |

**VERIFIED, and the sharpest single fact in this note:** backboardd *does* ask
for the display to be switched off, every boot, and the kernel silently refuses:

    ring63:1782  A5XELTE FB: display-off request ignored (keep_on)
    ring63:2634  A5XELTE FB: display-off request ignored (keep_on)
    ring62:1277  / 2437, ring61:…  same line, 1-2 per boot, and it also appears
                 in keyless boots (T21a row in work/boots.md)

The refusal is `a5fb_keep_on=1` in the packaged cmdline
(`xnu-src/iokit/Kernel/arm/SweetFramebuffer.cpp:619-641`), and the call still
returns `kIOReturnSuccess` with no status, so backboardd's model of the panel can
never be corrected by us. Meanwhile the panel keeps presenting frames: ring63
logs `display on` at :1212, the first off-request at :1782, and swaps
:1241…:2628 across and after it. So for most of the boot userland believes
"display off, digitizer disabled" while the panel is lit and showing the lock
screen — a state split that is exactly the environment E3 describes. Whether
`displayState` would have been `on` had we not lied is **UNKNOWN**; the honest
version of the loop is the thing to test (section 4).

---

## 2. `normalizedDigitizerRect:{{0,0},{1,1}}` — refuted as a suspect

**VERIFIED: E4 is a full-coverage normalized rect, not a degenerate one.** The
literal format string is in backboardd:

    /tmp/pra-bin/backboardd @0xc16e2:
    CAWindowServerDisplay:%p size:{%g,%g} scale:%g nativeRotation:%@
    normalizedDigitizerRect:{{%g,%g},{%g,%g}} external:%d

plus the property/ivar/setter names: `normalizedDigitizerRect` @0xba602,
`_normalizedDigitizerRect` @0xb23f3, `setNormalizedDigitizerRect:` @0xbd63f, and
type encoding `T{CGRect={CGPoint=dd}{CGSize=dd}},N,V_normalizedDigitizerRect`
@0xaec74 (**VERIFIED**).

The archive fragments reconstruct that line exactly: `{1080, 1920}` (size),
`scale:3`, `Rot`…`:0` (nativeRotation), `norm`+`edDigitizerRect:{{0,0},{1,1}}`,
`ex`+`d:0` (external:0), `LCD primary` (display name), all inside
tracev3 188900-189400 (**VERIFIED** bytes, `od -c`).

Arithmetic (`python3`, quoted):

    unit rect covers px: 1.0*1080 = 1080.0, 1.0*1920 = 1920.0
    1080/3 = 360.0, 1920/3 = 640.0            (points, i.e. what UIKit lays out)

So `{{0,0},{1,1}}` in *normalized* display space is the whole 1080x1920 panel:
the digitizer covers the display. **Do not publish a rect of `{0,0,1080,1920}`** —
in this field that would be a 1080-screen-wide rect *in units of the screen*, i.e.
wrong by 1080x. There is nothing to fix in E4, and the port must not "fix" it.

Where the value normally comes from (**INFERRED**): backboardd derives it from
the digitizer service's coordinate space versus the display bounds and publishes
it to CAWindowServer. A hand-rolled service with no elements overruns nothing,
because the normalised identity is the correct answer for a display-integrated
digitizer whose events are already 0..1 — which is what `touch()` produces:

    fLogicalW/fLogicalH = 1080/1920, fOffX=fOffY=0 on PRA (both board macros are
    defined, so the A5XELTE arm is the one that runs)
      work/0200/SweetHID-post0200.cpp:602-610
    nx = (x + fOffX) << 16 / fLogicalW, ny likewise
      work/0200/SweetHID-post0200.cpp:668-669
    python3: 540 -> 32768 (= 0.5), 1914 -> 65331 (= 0.99687)

and the display size SpringBoard saw is the same 1080x1920
(`CAWindowServerDisplay size:{1080,1920}`, tracev3 @189147; `SWEET FB: swap N
layer 0 surface … 1080x1920`, ring63:1241), so the coordinate space backboardd
normalises against and the space we normalise into agree. **VERIFIED consistent.**
The prompt's "presented 1125x2436" does *not* apply on PRA: 1125x2436 is the
`#else` (non-A5XELTE) arm, `work/0200/SweetHID-post0200.cpp:611-619` and
`xnu-src/iokit/Kernel/arm/SweetFramebuffer.cpp:190-201` (the `#elif
!defined(ARM64_BOARD_CONFIG_A5XELTE)` guard).

What *is* worth publishing about geometry, and is currently missing, is not the
rect: the service should carry the IOHIDFamily-documented surface description
**in addition to** the two raw numbers it already sets:

| key | type | value | anchor |
|---|---|---|---|
| `SurfaceDimensions` (dict) | `OSDictionary{ "Width": IOFixed, "Height": IOFixed }`, millimetres, 16.16 | `{68, 121} mm` (the 1080x1920 panel) | key names `xnu-src/iokit/Kernel/arm/hid/IOHIDEventServiceKeys.h:110` (`SurfaceDimensions`), `:120` (`Width`), `:130` (`Height`), units documented at `:101-109`; values already in the tree at `work/0200/SweetHID-post0200.cpp:602-610` |
| `SurfaceWidth` / `SurfaceHeight` (already set) | `OSNumber`, 16.16 mm | 68 / 121 | `work/0200/SweetHID-post0200.cpp:623-624`; the names are real userland keys (present in `.01`, `.03`, `.05` of the cache) |
| `DisplayIntegrated` (already set) | `OSBoolean` true | true | `work/0200/SweetHID-post0200.cpp:622`; key `xnu-src/iokit/Kernel/arm/hid/IOHIDKeys.h:82` |
| `MultitouchHostStateKeys` | `OSArray` of `OSString` | see 1b | **missing** — this is the real geometry/state gap, not the rect |

`reportInterval` deserves a check for the same reason: userland's service
diagnostic prints `reportInterval:%d` (section 3), the tree publishes
`kIOHIDReportIntervalKey` = `"ReportInterval"` = 10000 µs
(`work/0200/SweetHID-post0200.cpp:74`; key text
`xnu-src/iokit/Kernel/arm/hid/IOHIDDeviceKeys.h:182`). The recovered digits next
to that field are `0`, which is either a mangled `10000` or a real 0; **UNKNOWN**
until the next harvest prints the line intact (section 5).

---

## 3. `events:0` — a service-description snapshot, not a drop counter

**VERIFIED format string** (`dyld_shared_cache_arm64.05`, near offset 10513076,
in the IOHIDService/IOHIDEventSystem string cluster with `EventLog`,
`EventTypeCounts`, `PropertyCache`, `NextEventTimeStampDelta`):

    IOHIDService name:%s id:0x%llx primaryUsagePage:0x%x primaryUsage:0x%x
    transport:%s reportInterval:%d batchInterval:%d events:%d mask:0x%llx

That is the line E1 half-quotes. Consequences:

- `events:%d` is the **event-system service counter**, i.e. events this
  `IOHIDService` object has received, printed as part of the service's
  description (`%@`) when somebody logs the description. It is **not** a drop
  counter: the drop evidence in this project is the kernel side (`SWEET HID:
  queue stats … drop=0`, and the 16 KiB queue arithmetic in
  `HANDOFF_2026-11-22b.md`), and it says the opposite of "dropped".
- Because the description is built at print time and stored as one dynamic
  string, the `0` cannot be dated from the archive. The whole 10.4 MB archive
  contains **exactly one** `BKIOHIDService`/`IOHIDService` description (grep
  count 1 at tracev3 3761036), and it is the one that carries `Status: matched`
  — i.e. it was emitted on the *match* transition, microseconds after the
  service appeared, when 0 is the only possible value. **INFERRED (strong).**
- The neighbouring digits are mangled by the encoder:
  `…transport:SPU re| Interval:0 b|1 events:0 mask:0x| anderID …` (od at
  3761170-3761230). The literal is `reportInterval:%d batchInterval:%d
  events:%d mask:0x%llx`, so **which recovered digit belongs to which field is
  UNKNOWN** from `strings` alone.

What confirms either reading (**both cheap, no device risk**):

1. A second description for the same service id later in a boot where events were
   provably enqueued (T19/T21 conditions). `events:0` again → match-time
   snapshot; `events:N>0` → it is a live counter and the count is meaningful.
2. A proper tracev3 decode (OSLog catalog + `bv41` chunks) of
   `Persist/0000000000000001.tracev3` filtered on `subsystem ==
   com.apple.iohid`/`com.apple.backboardd`, which yields the record timestamp and
   the intact argument vector. **This single decode also settles section 5's
   list**, so it is the highest-value next step after 0201.

---

## 4. Patch plan 0201 (and 0202/0203 behind it)

Ordering is cheapest-first. 0201 changes **no behaviour**: it only makes the two
gates observable, because every guess below is currently unfalsifiable in a ring.

### 0201 — instrument the three interfaces (one patch, one boot, zero risk)

1. `xnu-src/iokit/Kernel/arm/SweetFramebuffer.cpp`, struct `AppleCLCD` near
   `:123` (next to `bool fPowerOff;`): add

       uint32_t fPowerReq;      /* how many RequestPowerChange calls */
       bool     fUserlandOff;   /* what userland last asked for, keep_on or not */

2. same file, `case kSweetFBRequestPowerChange:` (`:619`), immediately after the
   `off` computation (`:621`), log **every** call with the raw argument, and
   record the request even when `keep_on` swallows it:

       IOLog("SWEET FB: powerreq n=%u arg=%llu off=%d keep=%d applied=%d\n",
           (unsigned)++fFB->fPowerReq, (unsigned long long)args->scalarInput[0],
           (int)off, (int)(have_keep && keep_on), (int)(off != fFB->fPowerOff));
       fFB->fUserlandOff = off;

   Keep the existing `A5XELTE FB: display-off request ignored (keep_on)` line
   unchanged (`:629`) — ring parsers and `work/claim-0198.md` key on it.

3. same file, `AppleCLCD::present()` (`:382`, after the `SWEET FB: swap %u layer`
   log at `:424`), prove the state split with one line per transition:

       if (fUserlandOff) { IOLog("SWEET FB: swap %u while userland-display-off\n", get32(rec, 0x50)); }

4. same file, `case kSweetFBNotifications:` (`:606`): log the type on **every**
   call, not only behind the once-per-selector guard at `:653`:

       IOLog("SWEET FB: notifyreg type %u func 0x%llx\n", type, (unsigned long long)args->scalarInput[0]);

5. `xnu-src/iokit/Kernel/arm/hid/SweetHID.cpp`, `IOHIDEventService::setElementValue`
   (`:238` in the tree, `:245` in the effective copy `work/0200/SweetHID-post0200.cpp`): log before
   refusing (do **not** yet change the return value):

       IOLog("SWEET HID: %s setElementValue page 0x%x usage 0x%x value 0x%x -> unsupported\n",
           getName(), (unsigned)usagePage, (unsigned)usage, (unsigned)value);

6. same file, `IOHIDEventService::setProperties` (`:244` tree, `:251`
   effective): log the pushed keys
   (`OSDictionary` iteration, cap at 8 keys per call):

       IOLog("SWEET HID: %s setProperties key %s\n", getName(), key->getCStringNoCopy());

7. `.github/workflows/xnu.yml`: add the marker asserts for `0201`
   (`strings -a "$kernel" | grep -F 'SWEET HID: setElementValue'` and
   `… grep -F 'SWEET FB: powerreq'`), per the AGENTS.md patch-hygiene rule.

**Ring lines that prove the gate moved** (next boot, `work/ring64-full.txt`):

    SWEET HID: SweetHIDTouch setElementValue page 0x… usage 0x… value …   <- backboardd IS pushing host state
    SWEET HID: SweetHIDTouch setProperties key …                          <- backboardd IS pushing properties
    SWEET FB: powerreq n=2 arg=0 off=1 keep=1 applied=1                    <- a second, refused off request
    SWEET FB: swap N while userland-display-off                            <- frames presented into a state userland calls "off"

**Ring lines that falsify the theory**

- No `setElementValue` and no `setProperties` line in the whole boot → backboardd
  never tries to configure the digitizer through the event service, so 1b/0202 is
  the wrong lever and the gate is downstream (SpringBoard routing) — stop there
  and go to section 5's tracev3 decode instead of writing 0202.
- `SWEET FB: powerreq` shows `arg=1` only (no `off=1`) in a boot where E3-type
  records still say `displayState: off` → the blank is entirely BLS-side and the
  framebuffer is not even consulted; the display-state lever is dead and only the
  host-state/wake path (0202) remains.
- `SWEET FB: notifyreg` lines appear with type ≠ 5 → someone does subscribe to
  display notifications, so implementing them (0203) becomes cheap and testable;
  their absence keeps 0203 speculative.

### 0202 — publish the host-state contract (only if 0201 shows the push)

All in `xnu-src/iokit/Kernel/arm/hid/SweetHID.cpp`:

1. `SweetHIDTouch::start()`, after the `DisplayIntegrated` property
   (`:448`, effective `:622`): publish `MultitouchHostStateKeys` as an `OSArray`
   of `OSString` containing exactly the keys we will honour — start with
   `ScreenOn`, `DigitizerSurfaceCovered`, `PocketTouchesExpected` (the three whose
   semantics we can implement from `fPowerOff`/board data). Add
   `WakeOnTapEnabled` only together with (3), never before.
2. `IOHIDEventService::setElementValue` (`:245`): accept the host-state usages,
   store them, log transitions, return `kIOReturnSuccess`; keep
   `kIOReturnUnsupported` for everything else (so we do not claim a capability
   we do not have).
3. `SweetHIDTouch::touch()` (`:680-731`, effective): set the display-integrated
   bit on the collection and on every child —
   `setIntegerValue(kIOHIDEventFieldDigitizerIsDisplayIntegrated, 1)`
   (field `IOHIDEventFieldDefs.h:161`, bit `IOHIDEventStructDefs.h:334`) — and set
   `kIOHIDEventFieldDigitizerWillUpdateMask` / `DidUpdateMask` so children are
   non-zero and the parent is non-zero, which is the shape backboardd's
   `ignoring subevent with nonzero didUpdateMask (on parent event with zero
   didUpdateMask)` check (`/tmp/pra-bin/backboardd` @0xcd925) expects from a
   real driver.
4. `SweetHIDTouch::start()`: also publish the `SurfaceDimensions` dictionary
   (section 2 table) next to the two existing numbers.

**Proof line:** backboardd's own per-event routing log becomes reachable —
`digitizer:%llX - display:%@ - %@` (`@0xcde28`) with our senderID, plus
`contacts now %@` (`@0xcdb2f`). **Falsifier:** events still drain (`queue stats
drop=0`) but `ignoring touch event` (`@0xcdd4d`) or `didn't see a previous touch
down … skipping event` (`@0xcda39`) starts appearing per event — then the defect
is the event shape, and 0202's item 3 plus path-index/`identity`/`index` values
are the next thing to change (our children set `Index=i`, `Identity=i+2`,
`transducerIndex=i+2`, `work/0200/SweetHID-post0200.cpp:712-715`).

### 0203 — stop lying about display power (last, because it can blank the panel)

1. Command-line change only for the test: drop `a5fb_keep_on=1` so
   `kSweetFBRequestPowerChange` actually applies (`:619-641`). The states then
   agree, and the ring finally shows `SWEET FB: display off` / `display on`
   (`:639`) instead of the refused-request line.
2. `xnu-src/iokit/Kernel/arm/SweetFramebuffer.cpp`: send the existing `notify()`
   mechanism (`:543-557`) on power transitions for every registered notification
   type, so a client that does register (see 0201's `notifyreg` line) learns the
   state. Do not invent a type number for this without a client: `SWEET_FB_NOTIFY_TYPES`
   is 8 (`:71`) and only type 5 is known to be vsync.
3. Publish read-back state so the divergence is queryable:
   `setProperty("DisplayPowerOff", fPowerOff ? kOSBooleanTrue : kOSBooleanFalse)`
   on transition, next to the existing properties (`:231-233`).

**Cost, stated plainly:** with `keep_on` gone the panel goes black when
backboardd asks for sleep, and if the wake path is broken (which is exactly what
0202 targets) the user has to reboot to get the UI back. Do 0201 and 0202 first.

---

## 5. What would definitively confirm this without another guess

One boot under 0201 (+0202 if 0201 is positive), one tracev3 harvest, then grep
these strings — each is a **verified** literal in the userland that produced the
original archive, so a hit is unambiguous and a miss is meaningful:

| grep string | where it lives | what a hit proves |
|---|---|---|
| `digitizerEnabled: YES` | `BKSHIDUISensorMode` description (BKS, `.05` @1324421 properties) | the winning sensor mode has the digitizer enabled **at the time of the harvest** — the gate in E3 moved |
| `reason: SB + ` **without** `backlight-off` | same record (`.05` reason builder `" + pocketTouchesEnabled(%@)"`) | the blank is no longer part of the winning reason list |
| `displayState: on` | same record (property `_displayState`) | SpringBoard's model of the display matches the lit panel |
| `normalizedDigitizerRect:{{0,0},{1,1}}` | `CAWindowServerDisplay` description (`backboardd` @0xc16e2) | geometry unchanged and still full-coverage (this is the *control*: if this value changes, something did move the rect) |
| `multitouchHostStateKeys: (` | same BKSHIDUISensorMode record | which host-state keys the winning mode activates; with 0202 it should list what we publish |
| `digitizer: tapToWake` / `digitizer: ` other value | `SBHIDUISensorModeAssertion` description (tracev3 @2625500, @4246500, @5243400 patterns) | which digitizer power mode SpringBoard asked for |
| `explanation: "idle timer"` | BLS transition record (tracev3 @6354256) | the blank was auto-lock; its absence with `displayMode:Off` means something else blanked |
| `digitizer:%llX - display:` with senderID `0x10000012a`(ish) | `backboardd` @0xcde28, **backboardd's own routing log — the first record that proves the event left backboardd toward a display** | the digitizer stream is being routed, not just drained |
| `contacts now ` / `contact %d presence:` | `backboardd` @0xcdb2f / @0xcdb0f | SpringBoard-visible touch contacts exist |
| `ignoring touch event` / `didn't see a previous touch down` / `ignoring subevent with nonzero didUpdateMask` | `backboardd` @0xcdd4d / @0xcda39 / @0xcd925 | the event shape is being rejected — a *positive* for the shape branch, and the exact line to fix against |
| `received tapToWake` / `send tapToWake to ` | `backboardd` @0xcda8d / @0xcd7f8 | the wake path ran, which is what `digitizerEnabled: NO` requires instead of normal delivery |
| `IOHIDService name:` … ` events:` with a non-zero count | IOHIDService description (cache `.05` ~0x10513076 cluster) | settles section 3 (live counter vs match-time snapshot) |
| `reportInterval:` value in the same line | as above | settles whether our `ReportInterval` = 10000 µs is read at all (section 2) |

Note on method: `strings` on `bv41` chunks cannot date or order records, so use
`grep -abo` offsets and compare them against the sensor-mode offsets above
(2625921 < 3920838 < 4106514 < 4465801 < 5243756 < 6358867) to place a hit in the
boot. A real tracev3 decode remains the only way to get timing and intact
argument vectors.

---

## 6. Summary table

| item | verdict | anchor |
|---|---|---|
| E4 "degenerate 1x1 digitizer rect" | **REFUTED.** It is `normalizedDigitizerRect` in 0..1 display space; `{{0,0},{1,1}}` = full 1080x1920 coverage, which is correct for a display-integrated digitizer whose events are normalized 0..1. Do not publish a pixel rect. | `backboardd` @0xc16e2 (format), @0xba602/@0xbd63f (property/setter); tracev3 @188900-189400; `work/0200/SweetHID-post0200.cpp:601-612, 668-669` |
| E3 `digitizerEnabled: NO` | **REAL BUT MISREAD.** It is a field of `BKSHIDUISensorMode`, the winning mode is SpringBoard's (score 4108 vs backboardd's baseline 1), and `display: off` is `displayState: off` in the same record. The blank that produced it is `explanation: "idle timer"`. It is the normal sleep mode, and it only costs us the taps that arrive while it is latched. | `.05` @1324421 (BKSHIDUISensorMode property cluster); tracev3 @2625921/@4106514/@6358867; tracev3 @6354256 |
| where the kernel must intervene | the **display-state** interface (which the port lies about: `keep_on` swallows the off request, no brightness selector, no power notification, unknown selectors answer zeros) and the **host-state/wake** interface (`setElementValue`/`setProperties` refused, `MultitouchHostStateKeys` absent, `IsDisplayIntegrated` never set on events) | `SweetFramebuffer.cpp:57-66, 231-233, 246-259, 619-641, 647-652`; `work/0200/SweetHID-post0200.cpp:245-255, 621-624, 680-731`; `IOHIDEventServiceUserClient.cpp:72-76, 486-504` |
| E1 `events:0` | **NOT a drop.** It is the IOHIDService event counter rendered in the service description, printed once in the whole archive, on the `matched` transition. Undatable from `strings`; a live-count sample at best. | cache `.05` IOHIDService format string; tracev3 @3761036 (single occurrence) |
| what proves the gate moved | `digitizerEnabled: YES` + a reason list without `backlight-off` in a `BKSHIDUISensorMode` record, plus `digitizer:<senderID> - display:` in backboardd's routing log | section 5 |

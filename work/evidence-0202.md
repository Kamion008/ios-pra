# EVIDENCE — 0202 three-way verification (2026-11-23)

Patch `xnu/patches/0202-pra-hid-hoststate-contract.patch` (296 lines, index-stripped:
2 file sections, 0 `diff --git`/`index` lines, 7 hunks). Durable before/after:
`work/0202/SweetHID-pre0202.cpp` (875 lines) / `work/0202/SweetHID-post0202.cpp`
(1000 lines), `work/0202/IOHIDEventService-post0202.h` (base = the CI-0201 tree
header). All output below is captured output, re-run this session.

## 1. Leg 1 — GNU patch, seeded from the post-0201 CI tree (the base)

```
$ cp CI-tree/SweetHID.cpp -> /tmp/opencode/verify-0202/iokit/Kernel/arm/hid/
$ patch -p1 --fuzz=0 --dry-run < xnu/patches/0202-pra-hid-hoststate-contract.patch
checking file iokit/Kernel/arm/hid/IOHIDEventService.h
checking file iokit/Kernel/arm/hid/SweetHID.cpp
$ patch -p1 --fuzz=0 < xnu/patches/0202-pra-hid-hoststate-contract.patch
patching file iokit/Kernel/arm/hid/IOHIDEventService.h
patching file iokit/Kernel/arm/hid/SweetHID.cpp
$ cmp <resulting files> work/0202/SweetHID-post0202.cpp / work/0202/IOHIDEventService-post0202.h
GNU patch leg OK (fuzz=0, cmp rc=0, both files)
```

## 2. Leg 2 — FULL STACK, git apply, zero skips (the 0164 method, this patch's real base)

The CI sequence (`.github/workflows/xnu.yml:56-59` + blacktop dxb `build.sh:465-479`):
fetch pristine `xnu-8796.141.3` (apple-oss-distributions, commit 1b191cb),
copy `xnu/patches/*.patch` + `*.sh` in, run every `*.sh` (stage scripts) with
`MACHINE_CONFIG=PRA MACOS_VERSION=13.5`, then `for PATCH in *.patch; do
git apply --check "$PATCH" && git apply "$PATCH"; done` — a failed `--check`
SKIPS silently (that is the hazard AGENTS.md warns about).

```
$ git clone --branch xnu-8796.141.3 https://github.com/apple-oss-distributions/xnu.git /tmp/opencode/xnu-pristine
warning: ... not a commit! ... 1b191cb ... (detached HEAD)
$ PATH=.../fakebin:$PATH MACHINE_CONFIG=PRA MACOS_VERSION=13.5 bash -c 'for SCRIPT in *.sh; do bash "$SCRIPT"; ...; done; ...for PATCH in *.patch; do git apply --check ... && git apply ...; ...'
stage scripts OK
sweet_hfs staged OK          <- 0026 fetched hfs-627.100.6 (MACHINE_CONFIG gate passed)
--- full-stack apply done, skips: 0 ---
```

**ZERO SKIPS across all 193 patches** (first run had `MACHINE_CONFIG`/
`MACOS_VERSION` unset => 0026 exited early => 0031/0041 skipped for missing
`bsd/sweet_hfs/` - that run is superseded by this faithful one; a fake `xcrun`
was needed only because the host is Linux, CI runs macOS natively).

Then the byte checks on the full-stack tree:

```
$ cmp iokit/Kernel/arm/hid/SweetHID.cpp work/0202/SweetHID-post0202.cpp        -> rc=0
$ cmp iokit/Kernel/arm/hid/IOHIDEventService.h work/0202/IOHIDEventService-post0202.h -> rc=0
$ cmp iokit/Kernel/arm/SweetFramebuffer.cpp <CI-0201 tree>                      -> rc=0   (0202 touches no FB file)
```

## 3. Leg 3 — already-applied discrimination (the skip detector, AGENTS.md:44-49)

On the post-0202 full-stack tree:

```
$ git apply --check 0202-pra-hid-hoststate-contract.patch
error: patch failed: iokit/Kernel/arm/hid/IOHIDEventService.h:70
error: ... patch does not apply
already-applied git check rc=1          <- expect 1: a rc=0 here would make the
                                           CI `--check && apply` a skip, not a pass
$ patch -p1 --fuzz=0 --dry-run < 0202-...
Reversed (or previously applied) patch detected! ... skipping ...
already-applied gnu dry-run rc=1        <- expect 1
```

Both legs discriminate: the recorded rc=0 on a clean tree is real, not a skip.

## 4. Hunk arithmetic (python3 exact recount — the 0164 awk's job, done exactly)

An awk one-liner initially printed `hunk 1 ... ok=0` for the header hunk; the
python3 recount (context includes the blank context line ` ` that awk's `/^ /`
missed because it is `" \n"` but the awk `NF==0` branch counted it into ctx of
the WRONG hunk) shows every count consistent:

```
hunk 1: ctx=6  add=10 del=0  -> old=6/6   new=16/16  OK     (header: _hostState[8])
hunk 2: ctx=6  add=43 del=6  -> old=12/12 new=49/49  OK     (setElementValue accept)
hunk 3: ctx=6  add=27 del=0  -> old=6/6   new=33/33  OK     (setProperties honour)
hunk 4: ctx=6  add=40 del=0  -> old=6/6   new=46/46  OK     (MultitouchHostStateKeys+SurfaceDimensions)
hunk 5: ctx=6  add=1  del=0  -> old=6/6   new=7/7    OK     (cumask decl)
hunk 6: ctx=6  add=14 del=0  -> old=6/6   new=20/20  OK     (child Will/DidUpdateMask)
hunk 7: ctx=6  add=13 del=0  -> old=6/6   new=19/19  OK     (collection mask + once-per-boot log)
all hunks consistent: True
```
Adds total = 10+43+27+40+1+14+13 = 148, deletes = 6 (the 0201 comment block
replaced). awk count: `grep -c '^+'` header=11 (10 + +++ line) hid=139 (138 + +++
line); `grep -c '^-'` = 1 (---) + 6 (0201 comment) — consistent.

## 5. Compile-surface check (the APIs used, located in the tree)

- `OSSymbol::isEqualTo(const char*)` — `libkern/c++/OSSymbol.h:398` (OSSymbol is
  `final : public OSString`, :88). Used as `key->isEqualTo("ScreenOn")`.
- `IORegistryEntry::setProperty(const OSSymbol*, OSObject*)` — IORegistryEntry.h:304.
- `OSSymbol::getObject(dict)` -> `OSDictionary.h:757`.
- `OSString::withCString` returns `OSPtr<OSString>` (OSString.h:176); the SAME
  file already assigns it into a raw `OSString*` (`return OSString::withCString("SPU")`
  at post-base :370, `OSString *transport = getTransport()` :67) — the pattern
  compiles in this exact TU.
- `OSNumber::withNumber(...,32)`/`OSBoolean::isTrue()`/`unsigned32BitValue()`
  already used by the 0201-era start() (:84-85).
- Update-mask constants: `kIOHIDDigitizerEventUpdate*Mask` IOHIDEventTypes.h:577-605;
  fields `WillUpdateMask`/`DidUpdateMask` IOHIDEventFieldDefs.h:157+ (reachable
  via IOHIDEventTypes.h:150), struct slots IOHIDEventStructDefs.h:376-377.
- Keys: `kIOHIDSurfaceDimensionsKey`/`kIOHIDWidthKey`/`kIOHIDHeightKey`
  IOHIDEventServiceKeys.h:110/120/130 (IOHIDProperties.h:27 included via
  IOHIDKeys.h:32, which SweetHID.cpp includes at :29).

## 6. Marker existence in this patch's source (CI asserts strings in the BUILT kernel)

Contiguous format-literal tails (the 0201 lesson: the %s name sits before them):

```
'hoststate keys published'         -> line: IOLog("SWEET HID: hoststate keys published (ScreenOn ...
'-> accepted (was %u set %d)'      -> line: ... value 0x%x -> accepted (was %u set %d)\n"
'keyvalue %s = %u'                 -> line: IOLog("SWEET HID: %s keyvalue %s = %u\n" ...
'SWEET HID: digitizer update masks set' -> line: IOLog("SWEET HID: digitizer update masks set\n")
```
All four are contiguous in the source literals (verified by grep -F on the patch
file: 4/4 present). The workflow asserts (`.github/workflows/xnu.yml`, added
this session) grep the same four strings in the built kernel.

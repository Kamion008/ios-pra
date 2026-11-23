# CLAIM: 0201 (host-state/display-power instrumentation — the T22 fork boot)

Author: session 2026-11-23 (post HANDOFF_2026-11-23d). Claim for the landed patch
`xnu/patches/0201-pra-hid-hoststate-instrumentation.patch` (commits adb28b3 + the
workflow-only marker fix 7f20894), flashed as T22 at 2026-11-23 14:42:18 UTC.
Companion records: work/boots.md T22 row, work/0202-design.md (the prep behind the
fork), HANDOFF_2026-11-23d.md (the causality evidence this boot builds on).

PURPOSE. The causality question is already ANSWERED (ring64 + the tracev3 harvest:
a wake event re-enables the digitizer; SpringBoard's asserted LockButton sensor-mode,
score 4108, carries digitizerEnabled: YES / displayState: on; the idle timer's
backlight-off mode carries NO / off). What is NOT known is whether backboardd
configures our digitizer through the event service at all — the lever 0202 would
pull. 0201 changes no behaviour except marking digitizer events display-integrated;
it makes the three interfaces observable so ONE boot decides the fork.

K1 (VERIFIED, source): WHAT 0201 INSTRUMENTS. Three interfaces, per the patch:
(1) every kSweetFBRequestPowerChange call logged with raw arg / off / keep / applied,
and fUserlandOff recorded even when keep_on refuses; frames presented while
fUserlandOff logged (`SWEET FB: swap N while userland-display-off`);
(2) every kSweetFBNotifications registration logged (`SWEET FB: notifyreg type`);
(3) the refused setElementValue logged with page/usage/value (return unchanged),
setProperties keys logged (cap 8/call), and kIOHIDEventFieldDigitizerIsDisplayIntegrated
set on the collection AND every finger child, logged once per boot. Anchors:
0201 patch hunks; work/0202/SweetHID-pre0202.cpp:243-262 (setElementValue/setProperties),
:719-732,:763 (the event field).

K2 (VERIFIED, commands): BUILD AND PACKAGE PROVENANCE.
- `gh run view 45075755692` = SUCCESS (build 7m20s, all steps green). The earlier
  run 45074770951 (work/ci-0201.log) failed ONLY at "Verify PRA preemption
  diagnostics are linked": its assert grepped 'SWEET HID: setElementValue', which
  is not contiguous in the binary (the format string is 'SWEET HID: %s
  setElementValue page 0x%x ...'). 7f20894 fixed the assert to 'setElementValue
  page 0x%x' and touched ONLY .github/workflows/xnu.yml (git show --stat: 5+/1-).
  The kernel artifact in out/ci-0201/ (sha256
  5b3aae4013015b67c6634a38e3df2931be2b39fca411936985d93fdf7dddc7bb, 17,224,616 B)
  was downloaded from the first run; its kernel source is identical to the SUCCESS
  run's. work/ci-0201b.log's "build failed" tail is a NETWORK DROP while polling
  ("error connecting to api.github.com"), not a build failure.
- Package reconstruction (python3, tools/mkpayload.build on the CI kernel + the
  packaged ADT + the T21c cmdline): all 10 segment tables SAME, all 10 segment
  data regions BYTE-IDENTICAL to shim/pra/outxnu/payload.bin; header, entry,
  virt_base, cmdline SAME. The ONLY delta is the ADT's 64-byte random `om-seed`
  property (mkadt_pra.py regenerates it; dram-base/size identical: 0x88000000 /
  0x40000000 = 1024 MiB). kernel.gz == Image (sha256
  77da9626918d6f9d52a05694e5b2332426fdfe2c00c12d7c45bee24d23c8ed50); the SWEETXNU
  payload sits at Image offset 0x80000 and is contained in the gzip'd image body.
- Cmdline gate (python3, the scripts' own method: gzip payload at img+0x800,
  string at +0x48): 532 B, byte-equal to work/0198/cmdline.txt + ' prakeyevery=30',
  all 11 critical args + pratouch/pratouchreset/pratouchdbg/pratouchselftest/
  prapowerkey=900/prakeyevery=30/sweetsample=SpringBoard,backboardd PRESENT.
- Flash (tools/pra_flash_skip.sh, p27 only): image sha256
  bd2ad84a05398b88dbd8d122d003c89144da61a2d9b7de7111fccd2738b7e4d6, readback
  IDENTICAL, reboot 14:42:18 UTC. Battery 93% at flash (adb sysfs).
- All 0201 markers present in the decompressed payload: 'setElementValue page
  0x%x', 'SWEET FB: powerreq n=', 'SWEET FB: notifyreg type', 'digitizer events
  marked display-integrated', 'SWEET HID: powerkey arm' (python3 substring search).

K3 (VERIFIED, commands): BASE CORRECTION — the 0201 header's framebuffer derivation
was WRONG, the patch and the flashed kernel are unaffected. The header claims the
CI tree "does not have the prague_gpu_present_slot block at this point in the
stack" and derives work/0201/SweetFramebuffer-pre0201.cpp without it. In fact
0171-pra-gpu-consolidated.patch ADDS that block to SweetFramebuffer.cpp (patch
section --- a/iokit/Kernel/arm/SweetFramebuffer.cpp at :2303, extern decls at
:2313), the CI kernel carries 12 'prague_gpu/sweetfb_gpu' strings, and the real
build tree (/tmp/opencode/ci-tree-0201/buildtree.tgz, downloaded 2026-11-23 15:06;
tgz == src byte-for-byte for both files) HAS the block. 0201 applied cleanly to
both bases because its hunk contexts do not overlap the GPU additions (GNU patch
offset, not fuzz). CORRECTED durable bases for 0202: work/0202/SweetHID-pre0202.cpp
(== work/0201/SweetHID-post0201.cpp, cmp rc=0) and work/0202/SweetFramebuffer-pre0202.cpp
(== the CI tree file). Round-trip proof: CI post-0201 files, `patch -p1 -R --fuzz=0`
of 0201 then `patch -p1 --fuzz=0` of 0201, cmp rc=0 against both bases. The GPU
path is boot-arg gated (`sweetfb_gpu`, SweetFramebuffer.cpp:228-229 fGpu = gpu != 0);
the T22 cmdline does not carry it, so fGpu=false and the CPU row copy runs — the
GPU block changes nothing this boot. DO NOT use work/0201/SweetFramebuffer-*0201.cpp
as a 0202 base; it is missing 0171's GPU block.

K4 (PREDICTION, the fork — ring65 decides): the push lines appear. backboardd's
BKHIDUIHostStateDigitizerServiceWrapper (string @0xd04df in the T21-era backboardd)
configures the digitizer through setElementValue:forUsagePage:usage: (@0xbcb6e) and
_queue_applyCachedPropertiesToMultitouchService: (@0xb30c1). If the ring carries
`SWEET HID: SweetHIDTouch setElementValue page ...` and/or `setProperties key ...`,
0202 is the right lever and the logged page/usage values name its accept-list.
If NO such line appears in the whole boot, 0202 is the WRONG lever — stop and do
the tracev3 route-log decode (digitizer-gate-2026-11-22.md §5: `digitizer:%llX -
display:` @0xcde28 with our senderID, `contacts now` @0xcdb2f) instead. Secondary
predictions: 1-2 `powerreq ... off=1 keep=1` lines (ring62/63 held 2 refused
off-requests each); `notifyreg` absent or type=5 only (no subscriber has ever
registered in rings 60-63); the display-integrated marker ONCE, before the first
touch line; the T21c key controls unchanged (arm line, 30 s cadence, head==64*enq).
IMPOSSIBLE state that would mean 0201 did not land: 'display-off request ignored
(keep_on)' present with zero 'SWEET FB: powerreq' lines (same case arm).

K5 (VERIFIED, method): MARKER DISCIPLINE. The 0201 lesson: assert on a substring
that sits CONTIGUOUSLY in the binary. 'SWEET HID: setElementValue' does not exist
(the %s name sits between prefix and verb); 'setElementValue page 0x%x' does.
Every 0202 marker must be chosen the same way and checked against the built kernel
before the CI assert is written. The workflow now greps 'setElementValue page
0x%x', 'SWEET FB: powerreq', 'SWEET HID: digitizer events marked display-integrated'
(.github/workflows/xnu.yml, 7f20894).

K6 (SCOPE): what T22 does NOT prove. A push line proves backboardd ATTEMPTS
configuration through the event service — not that accepting it enables the
digitizer from boot; that is 0202's test (and the keyless boot after it). The
wake causality itself is already evidence-answered (HANDOFF_2026-11-23d); T22
keys stay ON (prapowerkey=900 prakeyevery=30) as the positive control and the
working workaround, mandatory until 0202 lands. Touch-from-boot with NO synthetic
key remains the deliverable, recorded only when a keyless boot demonstrates it.

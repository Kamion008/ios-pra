# CLAIM: 0193 (the PRA touch SURFACE geometry)

author: Buffy (Freebuff session 2026-11-21; reviewed on
opencode/deepseek-v4.1-flash-free per user direction). The patch is
emitted by work/gen0193.py from work/ci193/pre0193 = the post-0192
SweetHID.cpp; three-way verify PASS + structural assertions.

Base evidence: boot T16 (ring57, evidence 1) + the donor herolte proof
(evidence 2) + the framebuffer constants (evidence 3) + the patch and
its verify (evidence 4).

The patch (xnu/patches/0193-pra-touch-surface-geometry.patch) claims:

K1: THE T16 RESULT. The kernel->userland delivery is FULLY proven:
    mapped, notified, enqueued, drained (641 events x 236 B = 147.7 KiB
    through the 16 KiB queue, drop=0, head==tail at every sample,
    senderID 0x100000126). The UI still ignores touches. The AKS sel-8
    loop is background churn (exonerated: one-shot triads, no touch
    correlation). The blocker is the touch->display correlation.

K2: THE DONOR PROOF. The S7 (HEROLTE) board reaches the iOS home
    screen with WORKING touch on the SAME SweetHID delivery path
    (research/herolte-ref, patch 0211). Its two differences from PRA:
    1. CLAMP: herolte clamps the finger to the REAL panel
       (fPanelW/fPanelH = the IC's native res) then normalizes against
       the logical display; PRA clamps y against fLogicalH (the
       1125x2436 logical display, not the 1080x2400 panel).
    2. SURFACE mm: herolte publishes its REAL physical mm (64x113 for
       the S7's 5.1-in panel); PRA publishes the iPhone X's 68x151 mm.

K3: THE PRA PANEL. The framebuffer's own constants (SWEET_FB_DOT_PITCH
    = 424 ppi, 1080 px across 5.2 in) give the real panel: width
    132.08 mm (5.2 x 25.4), height 143.77 mm (2400 / 424 x 25.4) -
    vs the published 68x151 mm (the iPhone X's). A 132x144 mm touch
    surface claimed as 68x151 mm is a ~2x x-scale error and a wrong
    aspect ratio.

K4: THE FIX - the herolte pattern.
    1. start(): fPanelW=1080 fPanelH=2400, offsets (logical-panel)/2.
    2. touch(): clamp to the panel (y to 2399, not 2435).
    3. SurfaceWidth=8655995 (132.08 mm), SurfaceHeight=9422111
       (143.77 mm) in 16.16 - the REAL panel.
    Falsifier: touch works = the surface/correlation rung; still dead =
    the normalization was not the (only) cause.

K5: KNOWN LIMITS. The events carry 0..1 fixed coordinates normalized
    over the LOGICAL display (nx/ny, SweetHID.cpp touch()), so the mm
    surface may be a reported physical size rather than the coordinate
    transform - the review probes this. The y-clamp change affects only
    y>2399 (off-panel anyway); the x-clamp is a no-op. The behavior
    change for in-panel touches is therefore small unless the mm
    surface IS the correlation key.

REVIEW: round 1 (deepseek-v4.1-flash): pending the subagent verdict on
the mm hypothesis (normalized coords vs published mm) and the herolte
precedent (whether 0211's geometry was the fix that made touch work or
cosmetic).
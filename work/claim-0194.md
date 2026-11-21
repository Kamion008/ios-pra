# CLAIM: 0194 (the touch panel init in the COMPILED arm)

author: Buffy (Freebuff session 2026-11-21). The patch is emitted by
work/gen0194.py from work/ci193/pre0193 + 0193; three-way verify PASS +
structural assertions. Base evidence: evidence-0194.md (T17 ring58, the
CI build log, the T17 kernel disassembly).

The patch (xnu/patches/0194-pra-touch-panel-init.patch) claims:

K1 (VERIFIED): THE RING PAIR. ring58 has, at consecutive lines 2501-2502:
    `PRA touch: hid inject slot=0 down x=550 y=1911`
    `SWEET HID: touch 0 down at -1,-1 edge`
    So pra_touch_inject passed the REAL IC coordinates (550,1911) and
    SweetHIDTouch::touch() printed (-1,-1). The corruption is inside
    touch(), not in pra_touch.c, and not a symbol-linkage problem:
    sweet_hid_touch is a real symbol in the kernel (`_sweet_hid_touch`,
    0xfffffff007a5c9e0) and the SAME touch() body ran (it printed).

K2 (VERIFIED): THE COMPILED ARM. The T17 build log's SweetHID.cpp
    compile line (work/ci193/fail/build.log:34742) contains BOTH
    `-DARM64_BOARD_CONFIG_PRA` and `-DARM64_BOARD_CONFIG_A5XELTE`.
    Therefore `#if defined(ARM64_BOARD_CONFIG_A5XELTE)` in
    SweetHIDTouch::start() is TRUE and the A5XELTE arm is what runs on
    PRA. The T17 kernel cc83d49c confirms it: start() loads
    (1080,1920,0,0) from the const pool @0x702e720 into
    [x19,#0xb0] (fLogicalW/H, fOffX/Y), and writes the property
    SurfaceHeight = 0x790000 = 121 << 16 (the A5 arm value).

K3 (VERIFIED): THE UNINITIALIZED PANEL. 0193 added fPanelW/fPanelH only
    to the `#else` arm. In the compiled A5XELTE arm start() has NO store
    to [x19,#0xc0] (fPanelW) or [x19,#0xc4] (fPanelH) - the only store
    near the geometry is `str q0, [x19, #0xb0]`. touch() then loads
    those slots for the clamp:
    ```
    ldr  w8, [x19, #0xc0]      ; fPanelW
    sub  w9, w8, #1
    cmp  w8, w23               ; panelW vs x
    csel w23, w23, w9, gt      ; panelW > x ? x : panelW-1
    ```
    With fPanelW = 0 the condition is false and the result is 0 - 1:
    ```
    $ python3 -c 'print("0 - 1 =", 0-1)'
    0 - 1 = -1
    ```
    The same block does it for fPanelH. Hence EVERY coordinate becomes
    -1,-1, which is exactly the ring58 pair in K1. This also explains
    the "edge" suffix: -1 < SWEET_TOUCH_EDGE_PX.

K4 (VERIFIED): 0193's MM VALUE WAS WRONG FOR THE COMPILED ARM. 0193 made
    SurfaceWidth unconditional 8655995 (132.08 mm), computed as
    `5.2 * 25.4` - but 5.2 inches is the PRA's DIAGONAL, not its width.
    The framebuffer's 424 ppi gives
    ```
    $ python3 -c 'print(round(1080/424*25.4, 2))'
    64.7
    ```
    The working A5 board (same 1080x1920 panel) publishes 68x121 mm.
    At T17 the compiled arm actually published 132x121 mm (width from
    0193, height from the A5 arm) - an inconsistent 2x x-scale.

K5 (INFERRED): THE FIX. 0194 initializes fPanelW/fPanelH in BOTH arms:
    - compiled A5XELTE arm: panel 1080x1920, logical 1080x1920, offsets
      0, surface 68x121 mm (the working A5 donor's real geometry);
    - else arm: keeps 0193's 1080x2400 and 132x144 mm.
    It also prints the one-time `SWEET HID: panel arm A5XELTE 1080x1920`
    marker (CI strings guard) and makes the surface marker print the
    branch's actual mm/panel. No other function changes.
    INFERRED (not yet booted): with fPanelW/H = 1080/1920 the clamp
    passes the real coordinates through and the touch events carry
    550,1911 instead of -1,-1. The UI reaction is the falsifier.

K6 (UNKNOWN): whether real coordinates are the LAST blocker. T16 proved
    the queue delivery (641 events, drop=0, drained); with coordinates
    fixed, the remaining unknown is backboardd's routing to SpringBoard.
    The T18 ring decides.

FALSIFIER: after 0194 boots and the screen is touched, ring59 shows
`SWEET HID: touch ... at 550,1911` (real coords) = K5 HIT; still -1,-1 =
the compiled source differs from this tree; real coords + UI dead = the
blocker moves to backboardd/SpringBoard (K6).

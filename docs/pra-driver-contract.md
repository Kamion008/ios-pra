# PRA driver contract — hi6250 pinctrl

One driver, one patch, one agent. Everything not in here must be asked, not
assumed. Read §1–§5 before touching a file.

## 1. What is being built

- Driver: **hi6250 pinctrl** — the four `pinctrl-single` register blocks of the
  Kirin 655, exposed as one IOKit service.
- Purpose, one sentence: let later drivers (SD root, keys, console) read and,
  behind an explicit opt-in, set pin mux/conf without poking registers through
  the loader shim.
- New code or port? **New code.** Shape copied from
  `xnu-src/iokit/Kernel/arm/SweetBattery.cpp` (IOService subclass + `reg`
  property mapping) and matching via the config-table pattern of
  `xnu/patches/0132-pra-platform-expert-name-match.patch`.
- Patch number and slug: **`0135-pra-hi6250-pinctrl.patch`** — `0134` is taken
  by the preempt/idle diagnostic that is already committed, do not reuse it.

**Read-only by default.** `start()` maps the blocks and publishes properties;
it must not write a single pinmux register. Writes only through an explicit
call that the main agent can enable later. A wrong mux can kill eMMC, display
or the console, and this driver is not worth losing the boot for.

## 2. Hardware facts

Do **not** restate registers here. Point at the audited source:

- `docs/pra-facts-review.md` — bases, IRQs, RAM hole, clock rates
- `live/dmesg.txt` lines 456–459 — the four stock registrations:
  - `fff11000.pinmux`, 43 pins, size `0xAC`
  - `fff11800.pinmux`, 47 pins, size `0xBC`
  - `e896c000.pinmux`, 138 pins, size `0x228`
  - `e896c800.pinmux`, 141 pins, size `0x234`
- Absolute PAs: `0xFFF11000`, `0xFFF11800`, `0xE896C000`, `0xE896C800`.
  ADT `reg` uses the SoC-relative convention (`SOC_BASE = 0xE0000000`), so
  the offsets are `0x1FF11000`, `0x1FF11800`, `0x896C000`, `0x896C800`.
- Open question Q1: which block owns the SD-card and the console/key pins is
  **not** established from the stock DT yet. Until it is, writes stay off.

## 3. IOKit shape

- Class name: `PRAPinctrl` (PRA-only; do not reuse a `Sweet*` name).
- Superclass: `IOService`. Provider class: `IOPlatformDevice` — the platform
  expert creates nubs for `/arm-io` children, so the ADT node is enough.
- Match: add one entry to `gIOKernelConfigTables` in
  `iokit/KernelConfigTables.cpp`, guarded with `#if defined(ARM64_BOARD_CONFIG_PRA)`
  so A5XELTE/S8 tables stay byte-identical:
  `'IOClass' = PRAPinctrl; 'IOProviderClass' = IOPlatformDevice;
   'IONameMatch' = ('hisilicon,hi6250-pinctrl');`
- `start(provider)`: read the `reg` property exactly like
  `SweetCPU.cpp:77`, map with `ml_io_map()`; publish base/size per block as
  properties. Return false (no panic, no IOLog spam) if `reg` is missing.
- Probe order dependencies: none. It starts after the platform expert and
  before `IOFindBSDRoot`; it must not block, sleep, or create threads.

## 4. ADT

- Node path the driver matches: `/arm-io/pinctrl` (child of `arm-io`,
  name `pinctrl`).
- Properties: `compatible = 'hisilicon,hi6250-pinctrl'` plus
  `'hisilicon,hi6250'`; `reg` = four (offset, size) tuples in the order above.
- Does `tools/mkadt_pra.py` need a new node? **Yes**, and that file is shared
  with the main agent — **do not edit it**. State the lines; the main agent
  merges them after the driver compiles:

```python
    arm_io.children.append(mkadt.node('pinctrl', [
        ('compatible', mkadt.cstr('hisilicon,hi6250-pinctrl') +
         mkadt.cstr('hisilicon,hi6250')),
        ('reg', mkadt.u64(0x1FF11000, 0xAC, 0x1FF11800, 0xBC,
                          0x896C000, 0x228, 0x896C800, 0x234)),
    ]))
```

## 5. Build wiring

- Files to add (relative to `xnu-src/`): `iokit/Kernel/arm/PRAPinctrl.cpp`.
- Build-list entry (`xnu-src/iokit/conf/files.arm64`, next to the other
  `Sweet*` lines):
  `iokit/Kernel/arm/PRAPinctrl.cpp                     optional iokitcpp`
- **Add this entry last**, after the file compiles with the replay command
  below. Until then it stays out of the Makefiles and cannot affect anyone.

Compile check (one command per cycle; no CI, no flashing):

```sh
XNU_CC_CLANG=/usr/bin/clang \
XNU_CC_DXB=/Users/runner/work/ios-pra/ios-pra/dxb \
tools/xnu-cc.py /tmp/xnu-43018834356.log /tmp/pra-buildtree iokit/Kernel/arm/PRAPinctrl.cpp
```

`/tmp/pra-buildtree/xnu` is the tree to edit/compile in; mirror the final file
into `xnu-src/` and produce the patch from there.

## 6. File ownership

May edit:

- `xnu-src/iokit/Kernel/arm/PRAPinctrl.cpp` (new)
- `xnu-src/iokit/conf/files.arm64` (only the §5 line, only at the end)
- `xnu-src/iokit/KernelConfigTables.cpp` (only the §3 entry)

Must not edit:

- `PRA-LX1_PROGRESS.md`, `NOTES.md`, `AGENTS.md`, any other `xnu/patches/*.patch`
- anything in `live/` or `out/`
- `tools/mkadt_pra.py`, `tools/xnu-cc.py`, `shim/`
- other `xnu-src/` files; do not commit, `git add -A`, `git checkout`, `stash`
  or reset anything in `xnu-src/`

## 7. How it is delivered and checked

- Local XNU source is `xnu-src/` — a nested git repo whose HEAD already
  contains patches 0128–0134 and is clean; leave it clean of unrelated edits.
- CI does **not** see `xnu-src/`. `.github/workflows/xnu.yml` checks out this
  repo and copies `xnu/patches/*.patch` into blacktop's `dxb/patches/`. So
  local edits cannot break CI; only the patch matters.
- Deliverable: `xnu/patches/0135-pra-hi6250-pinctrl.patch`, produced with
  `git -C xnu-src diff -- iokit/Kernel/arm/PRAPinctrl.cpp iokit/KernelConfigTables.cpp iokit/conf/files.arm64`.
- Also deliver: the compile evidence (the `N of M files failed` line), and a
  plain list of every file touched.
- It must compile. An uncompiled driver is a draft, not a deliverable.
- Run compiles as **one batched command per cycle** (build + grep errors), not
  one shell call per file — every shell call needs user approval.
- It must not run `fastboot`, `adb`, `gh workflow run`, or anything that
  touches the phone or CI.
- It must not claim hardware behaviour. It has never booted this.

## 8. Definition of done

1. Patch applies cleanly to `xnu-src` at the current HEAD.
2. The new file compiles for `PRA` / Cortex-A53 (ARMv8.0, no LSE, no PAN) with
   the §5 command, and the reported failure count is 0.
3. Every file touched is listed, and nothing outside §6 was touched.
4. Open questions are written down, not guessed.

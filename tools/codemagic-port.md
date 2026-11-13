# Codemagic backup pipeline for the PRA XNU kernel

`codemagic.yaml` (repo root) is a **backup** pipeline ported from
`.github/workflows/xnu.yml`. Use it only when GitHub Actions cannot get a macOS
runner ("The job was not acquired by Runner of type hosted even after multiple
attempts" — GitHub-hosted macOS capacity). The GitHub workflow stays primary;
this file has **no push/PR triggers**, so it never runs automatically and never
burns minutes.

## What the pipeline does

Same recipe as `xnu.yml`, step for step:

| GitHub (`xnu.yml`)                        | Codemagic (`codemagic.yaml`)                                        |
|-------------------------------------------|---------------------------------------------------------------------|
| `workflow_dispatch` inputs                | `inputs:` (macos_version, kernel_config, machine_config, keep_going; same defaults) |
| `runs-on: macos-15`                       | `instance_type: mac_mini_m2` + `environment.xcode: 16.4` (image selection only) |
| Fetch build script (pinned `DXB_SHA`)     | identical `git init dxb; git fetch --depth 1 $DXB_SHA; checkout FETCH_HEAD` |
| `cp xnu/patches/*.patch *.sh dxb/patches/`| identical                                                           |
| PRA `sed` on `dxb/build.sh` (`ARCHS=arm64 VALID_ARCHS=arm64 OTHER_CFLAGS='-mkernel -nostdinc -Wno-packed -mcpu=cortex-a53 -march=armv8-a+crypto'`) + `grep -c` verification | identical (BSD `sed -i ''`) |
| `brew install jq gum bash cmake ninja` + `xcodes` stub | identical (stub created only if no real `xcodes` exists) |
| Deps step picks the lowest installed Xcode 15.x, sets `DEVELOPER_DIR`, `xcode-select -s` | "Select Xcode 15.x" script: picks the lowest `/Applications/Xcode_15*.app` / `Xcode-15*.app`, sets `DEVELOPER_DIR` (persisted to `~/.xnu_build_env` because each script section is a fresh shell), `sudo xcode-select -s`, `xcodebuild -version`, `xcrun --find iig`. **Fail fast** with a clear message when the image has no Xcode 15.x |
| Build (`rm -rf build/xnu.obj`, `rm -f fakeroot/.../kernel.*`, `MAKEFLAGS=-k bash build.sh`) | identical |
| `Collect` (`if: always()`) → `out/` + `SHA256SUMS` | publishing script (Codemagic publishing scripts always run — the `if: always()` equivalent) |
| "Verify PRA preemption diagnostics are linked" incl. the 0155 driver-strings guard (`_pra_preempt_notzero`, `PRA-PREEMPT cnt=`, `return_to_user` disasm, `PRA charger:`, `prai2c2`, `_pra_log_panic_flush`, `PRA MSG`) | publishing script, copied verbatim; runs only for `MACHINE_CONFIG=PRA`; a failure fails the build *after* the kernel is already on disk |
| "Check for ARMv8.1 LSE instructions" (exact `grep -E`/`awk`, writes `out/*.lse.txt`) | same publishing script, report-only, same literal tab pattern |

Deliberately **not** ported (GitHub-only value, keeps backup builds cheap): the
`buildtree.tgz` packaging, the KDK support-libs inspection, and the
`xnu-buildtree` artifact. CI stops at the kernel artifact, which
`tools/pra_package.sh` consumes.

Artifacts: `out/kernel.development.pra`, `out/*.lse.txt`, `out/SHA256SUMS`.
Codemagic bundles them into a single `<project>_<version>_artifacts.zip` on the
build page (only special types like .ipa arrive as separate files). Artifacts
are collected even when a guard fails the build, as long as the files were
written first (Codemagic docs / discussion #2506).

## Xcode 15.x on Codemagic — the finding

This is the one place the port cannot be a drop-in copy of GitHub:

- GitHub's `macos-15` runner image still carries Xcode 15.x, and xnu-8796
  **requires** an Xcode 15.x `iig` ("Xcode 16's iig emits `IORPC.kernelContent`,
  which xnu-8796 lacks" — see the comment on the `build` job in `xnu.yml`).
- Codemagic **removed every Xcode 15.x machine image** (macOS 13.5.2/Xcode 15.0
  through macOS 14.4.1/Xcode 15.4) from its shared pool on **2025-11-10**
  after brownouts — [discussion #3294](https://github.com/orgs/codemagic-ci-cd/discussions/3294).
  There is no "Additional Xcode versions" option in the current docs to get
  them back.
- The oldest image selectable today via `environment.xcode:` is **Xcode 16.4**
  on **macOS 15.5 Sequoia** (`mac_mini_m2` / `mac_mini_m4`),
  [specs-macos/xcode-16-4](https://docs.codemagic.io/specs-macos/xcode-16-4);
  current default images ship a single Xcode 26.x/27.x
  ([specs-macos/xcode-26-6](https://docs.codemagic.io/specs-macos/xcode-26-6);
  preinstalled list in [Xcode update policy](https://docs.codemagic.io/specs/xcode-update-policy)).
- Hence `xcode: 15.4` in `codemagic.yaml` would fail at machine provisioning
  and is not used. The workflow boots the Sequoia 16.4 image, then fails fast
  in "Select Xcode 15.x" unless it finds an Xcode 15.x app.

**The only self-service way to a kernel on Codemagic today:** let the build
install Xcode 15.4 itself — set `DXB_INSTALL_XCODE15: "true"` and provide
`XCODES_USERNAME` / `XCODES_PASSWORD` (Apple ID + **app-specific** password)
as secret variables; the pipeline runs `brew install xcodes` and
`xcodes install 15.4 --experimental-unxip` (~8 GB xip, +20–30 min). If that
ever stops working (Apple delisting 15.4, tooling breakage), the remaining
options are asking Codemagic support for a custom/dedicated image, or fixing
xnu-8796 for Xcode 16+ iig output (out of scope here).

## One-time Codemagic setup (UI)

1. codemagic.io → sign up/log in with the **individual** account (free tier =
   500 macOS minutes/month applies to personal accounts only, M2 machines).
2. **Add application** → GitHub → authorize → select `ios-pra` → project type
   **"Other"** (Codemagic will detect `codemagic.yaml` at the repo root).
3. Open the app → **App settings**: do **not** create/enable a webhook
   (Settings → Webhooks), and do not add a `triggering:` section — without
   defined events, builds start **only manually** (docs: "If no events are
   defined, you can start builds only manually"). Verify the workflow
   `xnu PRA kernel (Codemagic backup)` / id `xnu-pra-backup` appears under
   "Start new build".
4. Variables: none required for the default fail-fast build. Only if you want
   the Xcode 15.4 download path: create secret variables `XCODES_USERNAME`,
   `XCODES_PASSWORD` (App/Team variables), add their group name under
   `environment.groups` in `codemagic.yaml`, and set `DXB_INSTALL_XCODE15` to
   `"true"`.
5. No code signing, no Apple credentials, no "Additional Xcode versions"
   setting exists or is needed (see the finding above).

## Triggering when GitHub Actions fails

- **UI:** app → **Start new build** → branch (e.g. `master`) → workflow
  `xnu-pra-backup` → adjust inputs (defaults match the GH dispatch defaults) →
  **Start build**.
- **REST API:**

  ```bash
  curl -H "Content-Type: application/json" \
       -H "x-auth-token: $CM_TOKEN" \
       --data '{"appId":"<appId>","workflowId":"xnu-pra-backup","branch":"master"}' \
       -X POST https://api.codemagic.io/builds
  # -> {"buildId":"..."}; token: User settings → Integrations → API
  ```

  API starts use the input defaults (`13.5` / `DEVELOPMENT` / `PRA` / `-k`).
  The pip `codemagic` CLI is a code-signing/local-build tool, not a build
  starter — use UI or REST API.

## Minutes / cost

- GitHub's whole `xnu` run is ~8 min; the Codemagic M2 (8-core) should be in
  the same ballpark. Realistic budget per backup build: **~15–25 min**
  (clone + brew deps ~3–5 min, kernel build ~8–12 min, guards/LSE ~2–5 min).
- Free tier: **500 macOS minutes/month** on M2 for individual accounts →
  roughly **20–30 backup builds/month** free. Overages on M2 are $0.095/min
  (pay-as-you-go). The `DXB_INSTALL_XCODE15` path adds ~20–30 min →
  ~40–55 min/build → ~10 builds/month, and may need `max_build_duration`
  raised above 60.
- Sources: [pricing](https://docs.codemagic.io/billing/pricing),
  [machine types](https://docs.codemagic.io/knowledge-codemagic/machine-type).

## Open risks

- **Xcode 16.4 image is a dead end without the download path** — by design the
  default run fails fast in "Select Xcode 15.x" (cheap: ~2 min wasted).
- **Xcode 15.4 on macOS 15.5 Sequoia is expected to work but is unverified on
  Codemagic's exact image** (15.4 officially supports macOS 14+; watch the
  first real run). Codemagic could also drop the 16.4 image next — the
  `xcode:` key would then need a bump and the fail-fast message will say so.
- **`xcodes install` caveats:** needs an app-specific password (2FA), Apple
  can throttle the 8 GB download, `/Applications` install may need admin
  rights, and `--experimental-unxip` is not the stable extraction path.
- **Guard-failure artifact collection** relies on Codemagic collecting
  `artifacts:` from failed builds (community-confirmed in discussion #2506).
  If a guard ever fails and the zip is missing, rerun after fixing — the
  kernel is still in `out/` in the build workspace only, so do not rely on it.
- **Ordering differences vs GitHub:** guards run in `publishing:` (always-run)
  *after* the Collect step; a failing guard fails the build but the artifact
  globs are still evaluated afterwards. Codemagic stops a failing script
  section at the first error, so the preemption guard is wrapped in a subshell
  and the LSE report runs even when the guard failed (mirrors `if: always()`).

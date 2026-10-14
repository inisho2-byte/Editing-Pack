# Verification evidence and release gates

## Expanded candidate — 2026-10-14

The proposed v0.2.0-rc.1 candidate has passed 251 tests in a fresh anonymous-base
clone plus reviewed local payload, a new Python environment, newly installed
pinned packages, new user/browser profile and external workspace with spaces.
No skips or zero-test groups passed. Python access to original private sources,
skill stores and the earlier preparation environment was denied. This is one
Windows host, not an independent VM or a Node/browser security sandbox.

| Profile | Tests | Requirement |
|---|---:|---|
| Core | 209 | Locked core Python packages, FFmpeg/FFprobe |
| Style analysis | 12 | Optional pinned Pillow 12.3.0 |
| Graphics | 29 | Configured pinned HyperFrames, GSAP and Inter |
| Native 3D browser | 1, with 24 browser assertions | Configured Three 0.185.0, Puppeteer 25.13.0, Node and browser |

The core-only environment separately passed all 209 checks with no Pillow
installed. The synthetic clock and generated PCM/palette examples also pass in that
environment. The 3D profile verifies SwiftShader identity, nonblank frames,
A-B-A/shuffled seeking, lifecycle/disposal, live offsets and failed required
dependencies/fonts. Two fresh full-size software renders decoded identically at
1080 by 1920, 30 fps/three seconds, with no audio. The first took 296 seconds
including checks/QA; the repeat render took 235 seconds. Frames at 0.4, 1.5 and
2.6 seconds were inspected for actual folder/cards, readable draft labels,
lighting and shadows. This inspection is not human production review.

Hardware renders took about 19 seconds each and decoded successfully, but their
decoded video fingerprints differed. Hardware repeatability therefore FAILED;
hardware is experimental and cannot satisfy a deterministic production gate.
No waiver is applied. Software repeatability is the verified profile for this
synthetic scene, not a guarantee for arbitrary projects.

Tested resources: CPython 3.11.9, Node 26.8.1, FFmpeg/FFprobe 9.0.2, Chrome for
Testing 152.0.7977.30, HyperFrames 0.8.146, Three 0.185.0, Puppeteer 25.13.0,
GSAP 3.15.0, Inter 5.2.8 and Pillow 12.3.0. Task-owned rendering/browser processes
were checked after completion; none remained.

The [CI workflow](../.github/workflows/core.yml) runs core plus style (221 tests),
the synthetic walkthrough, dependency consistency, local source/link checks and
checksum-pinned Gitleaks. Actions remain commit-pinned, read-only, with no
persisted credentials, provider keys, private media, publication or artifact
upload. Graphics and native browser/encoded repeats are a mandatory manual local
release gate using all profiles and the documented examples; CI core/style alone
does not verify them. Any candidate change invalidates its freeze and requires
affected checks; final public CI and anonymous downloads are checked after the
exact candidate is approved and uploaded.

Hardware repeat failure from earlier private diagnostic work remains a known
limit. Hardware speed does not confer deterministic rendering. No production
waiver is invented. Native editors, paid calls, speech models and other operating
systems remain conditional or unverified. Every synthetic draft remains unready
for publication and never supplies a human approval.

## Published v0.1.0-rc.1 historical verification

Verified on 2026-10-11 in a new local checkout, Python environment, external workspace and user profile. Direct Python access to the original private workspace, vendor clones and prior developer environments was denied during the checks. This is filesystem/configuration isolation on one Windows host, not an independent operating-system VM or a Node/browser security sandbox.

| Check | Result |
|---|---|
| Locked core dependencies | Fresh binary-wheel installation and pip consistency check passed |
| Core runner | 184 checks passed; no skips |
| Optional graphics runner | 213 total checks passed; no skips |
| Documented synthetic walkthrough | Six-second, 180-frame draft; decode and decoded video/audio repeat comparison passed |
| Timing conversion | Source word at 5.3 seconds retimed to output 3.3 seconds using owned helpers |
| Contract examples | Seven synthetic shapes validated; no simulated approval consumed as authority |
| Authority refusals | Missing production authority, stale governing hash, missing caption treatment and unready publication refused |
| Runtime diagnostics | Ten fresh-process cases passed, including config/workspace overrides, missing tools and overlapping roots |
| Browser rendering | Three-second title card and six-second source-video composition encoded; title-card browser runtime/layout checks passed |
| Browser repeat comparison | Source-video composition decoded video/audio matched; readiness remained false |
| Process cleanup | No remaining task-owned Node, browser or FFmpeg processes found |

The source-video composition uses a neutral clock transcript with no semantic graphics cues. It verifies media, caption passthrough and browser encoding; semantic cue planning has separate unit/regression coverage. Title-card checks reported one nesting lint warning, no errors. Encoded sample frames were inspected; this inspection is not the required human production review.

Tested versions: Windows x64, CPython 3.11.9, FFmpeg/FFprobe 9.0.2, Node.js 26.8.1, HyperFrames 0.8.146, GSAP 3.15.0, Inter 5.2.8 and Chrome Headless Shell 152.0.7977.30. The tested Edge executable failed HyperFrames' Windows version preflight; configure the tested headless browser as described in [installation](installation.md).

Live WhisperX/model alignment, GPU workflows, paid provider execution, native editor import/readback, Linux/macOS and other Python versions remain unverified. A real job requires genuine forced alignment, approved hash-bound cuts, selected treatment, encoded evidence and exact-hash human review. Synthetic drafts intentionally remain unready for publication.

Private verification logs, media, local paths and configuration are excluded from this repository. This local verification does not authorize uploading the release candidate; public-clone verification follows publication.

### First-release CI

The first release's protected PR and three GitHub CI runs passed. Its workflow ran 184 core checks, synthetic media and source/privacy checks. The expanded candidate changes the profile count as described above; first-release CI does not certify new files. Fork PR execution remains `pull_request`, never `pull_request_target`.

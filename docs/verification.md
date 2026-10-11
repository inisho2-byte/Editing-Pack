# Fresh-install verification

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

## Prepared CI

The [Windows workflow](../.github/workflows/core.yml) runs locked core dependency checks, [source/link inspection](../scripts/check_source.py), checksum-pinned Gitleaks, the 184 core checks and the synthetic walkthrough. Actions are pinned by commit; permissions are read-only and checkout credentials are not persisted. It uses hosted Windows runners with external temporary dependencies/workspaces and no provider keys or private media. Fork pull requests use `pull_request`, never `pull_request_target`; no publication or artifact-upload step is included. Optional browser graphics are covered by local verification, not this core workflow. Local workflow commands are checked before candidate review; a real GitHub Actions run remains pending upload.

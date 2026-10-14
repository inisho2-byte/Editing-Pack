# Optional tools and services

Install only what you need into separate dependency directories/environments. [Installation](installation.md) gives tested pins; [tools manifest](../config/tools.manifest.json) records upstream URLs, revisions, terms and integrity. An upstream pin is not full integration verification.

## Graphics

The tested external packages are `hyperframes@0.8.146`, `gsap@3.15.0` and `@fontsource/inter@5.2.8`. Install with package scripts disabled, configure exact files and preserve upstream contents. The compositor verifies selected resource/license hashes before copying job resources. GSAP retains its header/custom terms; Inter's full OFL/copyright notice is copied beside job fonts. Neither is vendored here.

Node.js runs the CLI. Rendering needs an explicitly configured working browser; no browser is downloaded implicitly. Fresh synthetic rendering passed with Chrome Headless Shell 152.0.7977.30. The tested Edge executable failed the Windows version preflight. Follow [installation](installation.md) for the explicit browser download option. Media preparation needs FFmpeg; see [verification scope](verification.md).

The launcher discovers projects in `workspace/jobs/`. `--list` is read-only; `--open PROJECT_ID` starts an owned preview. Closing the launcher/interrupting CLI preview stops its process tree. Occupied port 3100 is refused. Never stop another user's server to make yours work.

## Alignment and models

The optional declaration pins WhisperX 3.8.6. Use its supported Python/platform and Torch setup in a separate environment before explicit model loading. Model licenses are separate from software terms. CPU is the owned backend's current choice; GPU availability does not automatically establish a verified GPU workflow.

Shared runtime places model caches in the external workspace. Model execution/downloads are unverified here. Supplied genuine forced-aligned words need an evidenced upstream process; sample JSON is not equivalent. Raw Whisper is diagnostic and cannot satisfy production alignment.

References: [WhisperX](https://github.com/m-bain/whisperX), [Whisper](https://github.com/openai/whisper). Review the pinned version's platform requirements before installing; do not silently substitute latest.

## Hosted images

The Ideogram utility supports structured prompt planning. Paid requests require `IDEOGRAM_API_KEY`, `--execute`, sufficient `--max-cost-usd` and `--acknowledge-api-terms`. Tests use mocks and do not contact the provider. Live execution is unverified.

Prices, availability, policy and output rights change. Verify current account terms/prices before approving cost; stored constants alone do not certify billing. Never paste a key into config, fixtures, issues or PRs. See [component guide](<../Editing_OS/Photo editing/Engines/Ideogram4_engine/README.md>).

## Native editors and bridges

| Integration | Setup and boundary |
|---|---|
| Resolve Lua/MCP | Optional pinned MCP v1 environment, explicit mailbox and verified empty project identity. Windows FFI bridge; SDK import/tool discovery tested, native execution unverified. |
| Final Cut | Matching installed DTD, xmllint and independent native import/readback. No complete verified macOS pipeline. |
| Premiere | Installed application/API and independent readback; conditional/unverified. |
| CapCut | Native interchange not implemented. |
| Blender bridge | External optional reference; no complete verified Editing-Pack integration. |

Do not run the connection test in a real working project. Its create/readback/delete operation requires explicit identity, an empty target and the editor's authorization. JSON config cannot inject environment variables into an already running native process; configure that process too.

## External specialists

The manifest references video-use, open-design, voicebox, OpenMontage, Playwright MCP and composition toolkits. Follow pinned upstream setup externally and retain their licenses/notices. OpenMontage's AGPL terms remain separate. Optional scheduling cannot replace the adapter's contracts or Quality readiness.

See [third-party notices](../THIRD_PARTY_NOTICES.md) and [capabilities](capabilities.md).

## Analysis and physical-object resources

Pillow 12.3.0 adds bounded image analysis. Three.js 0.185.0 and puppeteer-core
25.13.0 add the owned starter/browser regression profile alongside configured
HyperFrames 0.8.146, GSAP 3.15.0, Inter 5.2.8 and Chrome Headless Shell. Explicit
external installation commands are in [installation](installation.md). Three
and Puppeteer are MIT/Apache-2.0 respectively; GSAP has its own custom license
and Inter remains OFL. Installed assets are staged only into external jobs.
The nine studied 3D/web repositories are references, not installed integrations;
see [provenance](../Editing_OS/Skills/PROVENANCE.md).

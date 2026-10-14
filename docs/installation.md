# Installation

The published baseline is v0.1.0-rc.1; this update proposes v0.2.0-rc.1. The tested setup is Windows x64 with Python 3.11.9; other platforms still require fresh verification. Core tooling is installed separately from optional editors, models and graphics packages. Keep the toolkit checkout, dependencies and job workspace in separate folders.

## Core (PowerShell)

Run from the toolkit root. Use a dedicated sibling folder for the environment:

```powershell
py -3.11 -m venv ../editing-pack-env
../editing-pack-env/Scripts/python.exe -m pip install --only-binary=:all: -r requirements-core.lock.txt
if (-not (Test-Path -LiteralPath config/toolkit.local.json)) { Copy-Item config/toolkit.example.json config/toolkit.local.json }
```

Create the local config only when missing; preserve an existing one. Edit the ignored local config. Set `workspace_root` to a dedicated external folder, and set `tools.ffmpeg` and `tools.ffprobe` to the installed executable files. FFmpeg/FFprobe are external prerequisites; the toolkit does not install them. You can instead put both on PATH. No home directory scanning is used to find them.

```powershell
../editing-pack-env/Scripts/python.exe -B scripts/run_checks.py --config config/toolkit.local.json
```

The check runner requires FFmpeg/FFprobe for its synthetic media checks. Its logs and temporary files go under the selected external workspace. A passing test suite is not publication approval for any video.

## Optional graphics

With Node.js/npm installed, install packages in a separate dependencies folder:

```powershell
npm install --prefix ../editing-pack-graphics --ignore-scripts --no-audit --no-fund --save-exact hyperframes@0.8.146 gsap@3.15.0 @fontsource/inter@5.2.8
```

Set explicit file paths in `tools`: `node` to your Node executable; `hyperframes_cli` to `node_modules/hyperframes/bin/hyperframes.mjs`; `gsap_runtime` to `node_modules/gsap/dist/gsap.min.js`; both Inter font paths to `node_modules/@fontsource/inter/files/inter-latin-400-normal.woff2` and `inter-latin-700-normal.woff2`; `browser` to a working Chrome Headless Shell executable. The tested binary is Chrome for Testing 152.0.7977.30. The tested Edge executable failed HyperFrames' Windows `--version` preflight, so it is not a verified render setup. The font package must retain its LICENSE. HyperFrames must be version 0.8.146. This toolkit never invokes npx to install an unpinned package. Package scripts are disabled during installation.

```powershell
../editing-pack-env/Scripts/python.exe -B scripts/run_checks.py --config config/toolkit.local.json --graphics
```

Graphics checks exercise real media preparation and HyperFrames lint. Separate synthetic browser rendering and encoded repeat checks also passed in the [fresh verification](verification.md); your own video still requires its own final review. GSAP has its own custom license; Inter uses OFL 1.1. Generated job folders retain asset notices and hashes. These packages are not covered by the toolkit's MIT license. Review [third-party notices](../THIRD_PARTY_NOTICES.md).

## Explicit browser installation (optional)

If you do not already have a suitable headless browser, the pinned CLI can download one. This is an explicit network/download step, separate from core installation. From the toolkit root, run:

```powershell
$GraphicsCli = '../editing-pack-graphics/node_modules/hyperframes/bin/hyperframes.mjs'
node $GraphicsCli browser ensure
```

The CLI prints the installed executable path in its external user cache. Copy that exact path into `tools.browser`; do not copy the browser into the toolkit. This installation was tested with a fresh external user profile and HyperFrames 0.8.146. Browser downloads may change independently of the CLI pin; record the reported version for your job. For reproducible verification, use the tested version above. No browser is downloaded implicitly by the owned engines.

## Optional alignment, hosted images and native editors

WhisperX is a heavy optional backend. Use a separate Python 3.11 environment and `requirements-alignment.txt`, then check upstream platform and Torch requirements before loading models. The model cache belongs to the external workspace. Package installation does not download model weights here. WhisperX/model execution has not been verified by this setup step. Raw Whisper timing cannot substitute for production forced alignment.

Ideogram execution requires the `IDEOGRAM_API_KEY` environment variable and the existing explicit cost approval. Do not place keys in JSON, examples or Git. Setup checks do not call the paid API.

The Resolve mailbox/MCP integration is a guarded prototype, not a complete native editor. Install `requirements-resolve.lock.txt` into a separate environment only if you need it. Configure a mailbox inside the workspace and supply `EDITING_PACK_RESOLVE_MAILBOX`, `EDITING_PACK_RESOLVE_PROJECT_ID` and `EDITING_PACK_RESOLVE_PROJECT_NAME` to the Lua/native application process too. JSON config cannot configure another process automatically. The bridge requires an exact empty test project and preserves write/readback/cleanup guards. No native application is opened by the check runner. Premiere and Final Cut remain conditional on installed application APIs/DTDs; CapCut native interchange is not implemented.

Third-party specialist clones are optional, externally installed tools. They are not copied into this repository and do not grant Editing OS production authority.

## Optional style analysis and native 3D browser profiles

```powershell
../editing-pack-env/Scripts/python.exe -m pip install --only-binary=:all: -r requirements-style.lock.txt
npm install --prefix ../editing-pack-graphics --ignore-scripts --no-audit --no-fund --save-exact three@0.185.0 puppeteer-core@25.13.0
../editing-pack-env/Scripts/python.exe -B scripts/run_checks.py --config config/toolkit.local.json --style-analysis --graphics --3d-browser
```

Pillow 12.3.0 is optional; core/audio checks do not need it. Use the graphics setup
above first. Add `tools.three_module` pointing to
`node_modules/three/build/three.module.js` and `tools.puppeteer_entry` pointing to
`node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js`. The runtime requires
Three 0.185.0 and derives its matching core/addon files; retain package metadata
and licenses. Puppeteer 25 uses this entry rather than the older lib/cjs path.
Configured Node and browser paths must be executable files. No native Blender,
segmentation model or vendor clone is installed by this profile. See the
[new examples](new-capabilities.md) and [verification](verification.md).

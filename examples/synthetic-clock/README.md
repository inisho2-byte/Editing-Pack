# Synthetic clock walkthrough

Run this after [installation](../../docs/installation.md) and [configuration](../../docs/configuration.md). It needs the core Python environment plus FFmpeg/FFprobe with libx264, AAC and libass. It uses no network, model, recorded voice, hosted API, native editor or preview server. All generated files remain in a new job under your configured external workspace; no media is bundled in this repository.

From the toolkit root:

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
& $ToolkitPython -B scripts/synthetic_walkthrough.py --config config/toolkit.local.json
```

Expected: exit 0, `checks_passed: true`, `ready: false`, `publication_approved: false`. The result names your job and `exports/synthetic-DRAFT.mp4`. A gate refusal is successful tutorial behavior only when the script verifies its expected exit and reason. Any other error stops the walkthrough.

The default job is `jobs/synthetic-clock-demo`. Re-running never overwrites it. Use a different ASCII job name:

```powershell
& $ToolkitPython -B scripts/synthetic_walkthrough.py --config config/toolkit.local.json --job-name synthetic-clock-demo-2
```

The tutorial was exercised on Windows x64, Python 3.11.9 and FFmpeg 9.0.2, including a workspace path containing spaces. For this libass filter example, use a workspace path without apostrophes, square brackets, semicolons or commas. Other platforms remain unverified. Fix missing codecs/filters using your FFmpeg installation; the script never downloads a replacement. A failed run retains its diagnostics and partial job for inspection; retry with a new job name.

## What you will see

An eight-second generated test pattern and quiet oscillator tone becomes a six-second portrait draft. Blue and orange bars identify the two kept ranges. The captions are original generic test words; there is no recorded speech to align. The default historical caption look and fixture bars are unapproved draft treatments. No genre label or test run selects a production treatment.

| File in the external job | Meaning |
|---|---|
| `brief.md`, `fixture-status.json` | Generic brief, rights statement and explicit synthetic boundaries |
| `inputs/source.mp4` | Generated 360 by 640 test pattern, 30 fps, tone only |
| `work/source_words.json` | Manually authored test timestamps, not forced alignment |
| `work/timeline_map.json`, `work/retimed_words.json` | Actual owned editorial helpers convert source time to output time |
| `work/timing-demonstration.json` | Simulated timing inspection with expected offsets; not a production EDL or review |
| `work/draft-captions.ass`, `.captions.json`, `.qa.json` | Caption engine draft outputs; structural QA pass cannot certify real speech timing |
| `work/graphic-treatment.json` | Draft bar options and selected fixture recipe; no human selection or Graphics_engine production evidence |
| `contracts/production-context.json` | Schema-valid context with current governing-document hashes, deliberately incomplete production authority |
| `simulated-contracts/` | Seven schema-valid illustrative shapes, with fictional decisions and placeholder hashes |
| `exports/synthetic-DRAFT.mp4`, `synthetic-DRAFT-repeat.mp4` | Two actual encoded drafts; 180 frames each |
| `evidence/encoded-probe.json`, `quality-report.json` | Real encoded inspection and Quality Engine report; readiness remains false |
| `evidence/walkthrough-summary.json`, `cache/*.log` | Checked tutorial outcome and exact refusal diagnostics |

The caption engine's generic supplied-words provenance describes its input path, not how this fixture was obtained. Read the explicit synthetic metadata: these words were manually timed. The `.qa.json` adds that qualification. Neither a structural caption `pass` nor a matching decoded repeat render constitutes publication approval.

## Inspect the clock

Keep source `[0,3)` and `[5,8)`, removing `[3,5)`. Source second 5.3 becomes output second 3.3. The owned `retime_words` and `build_timeline_map` helpers perform this mapping. The script checks the offset and uses those output words for caption phrasing. See the [timing inspection](timing-inspection.example.json) and [generic brief](brief.example.md).

This directly demonstrates the clock calculation. Production still requires genuine forced alignment, a reviewed/hash-bound EDL and adapter-issued render authority; this tutorial does not create them. The FFmpeg fixture edit is deliberately confined to a non-production draft.

## Inspect the refusals

Read the corresponding external `cache/` logs:

1. `missing-authority.log`: live document hashes are correct, but mode/feature-required production evidence is missing.
2. `stale-authority.log`: a separate copied context has one deliberately stale document hash; the live toolkit document is never changed.
3. `missing-caption-selection.log`: production captions without explicit taste selection are refused. Only the explicit draft flag was used for the demonstration captions.
4. `publication-refusal.log`: the adapter refuses the encoded draft because the Quality Engine automated gate did not pass.

The Quality report deliberately lacks a complete production spec, realized evidence and human review. Expect multiple blockers, `automated_gate_passed: false` and `ready: false`. Decode integrity and decoded video/audio repeat comparison should nevertheless pass. This illustrates that an encodable, reproducible video cannot supply missing authority. It does not demonstrate a valid production spec or a real human review; follow the [production workflow](../../docs/workflow.md) for those.

## Contracts and treatment examples

The generated `simulated-contracts/README.md` marks every shape as a simulation. Approval booleans required by example schemas are fictional; hashes/references are placeholders. The tutorial validates their shapes only and never consumes them as authorization. Do not copy these approvals into real jobs.

[Draft graphic options](graphic-options.example.json) illustrate a simple treatment comparison. The fixture renders one fixed recipe; it records `selected_by_human: false`. Production graphics use the owned Graphics_engine, genuine post-cut timing and explicit taste-selection evidence. Their optional resource installation is separate.

## Rights and limits

The generator, generic fixture JSON and brief template are owned MIT examples. Explanatory prose here follows [license scope](../../LICENSE-SCOPE.md). The pattern, oscillator and bars are constructed locally; no third-party media, voices, models or font files are redistributed. Installed system fonts remain subject to their own terms. No external media attribution is required for these generated test shapes and tones.

Do not mistake these tests for verified real-content editing, real speech alignment, subjective review, native project interchange or a clean-install certification. Those require separate evidence. Keep generated media, local paths, logs and review records out of public issues and commits.

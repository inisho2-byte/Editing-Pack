# Tool Routing — The Specialist Layer

> The concrete tool map the handbook deliberately defers to here. Craft
> principles remain tool-independent. Current ownership, commands, prices,
> machine requirements, and replacement decisions live here; examples and
> finishing-surface constraints may still name tools elsewhere.
>
> **Doctrine (from Chapter 20):** the OS is a *conductor, not a one-man band*.
> Route each job to the right specialist and guard three seams: the post-cut
> timing clock, subjective treatment, and encoded-artifact readiness.

## The tool map — each tool does its one best thing

| Tool | Its one best job | Serves phase(s) |
|------|------------------|-----------------|
| **Whisper / WhisperX** | Transcribe **and** forced word-level alignment | 1 (understand), 7 (captions) |
| **video-use** | See / analyze footage, reframe, describe shots | 1 (understand), 12 (platform reframe) |
| **open-design** | Style tokens, palette, type, **LUTs** (grade options) | 8 (graphics), 13 (color) |
| **Hosted Ideogram 4 engine** | Production images with baked-in text, palette steering, and bounding-box layout | 8 (graphics), thumbnails / title cards / CTAs |
| **voicebox** | Text-to-speech / voiceover | audio / VO generation |
| **HyperFrames** | Deterministic **HTML → video** render (graphics, captions, motion) | 7, 8, 9 (render), any composited output |
| **Video editing engine** | Cleanup, sentence scoring, approved EDL, source→output retiming, render/QA | 2–6, 11, 14, 18 |
| **Contracts validator** | Versioned production context, editorial intent, taste, audio, EDL approval, experiment, and learning validation | every applicable phase boundary |
| **Orchestration adapter** | Live authority hashes, contract preflight, evidence envelopes, timing/EDL checks, and exact-artifact publication assertion | owned control plane |
| **Captions engine** | Word-aligned semantic phrasing, selected treatment, ASS/HyperFrames output, caption QA | 7, 18 |
| **Graphics engine** | Meaning-led graphic selection, selected treatment tokens, exact item anchors, mobile-scale type, full-stage PiP/3D choreography, graphics QA | 8, 9, 12, 18 |
| **Quality engine** | Encoded-artifact conformance, full decode, black/freeze/silence scans, audio measurement, repeat-render comparison, evidence + human-review gate | 14, 18 |
| **OpenMontage** | Third-party pipeline/checkpoint toolkit used only behind the owned orchestration adapter; its native caption/review path is not Editing OS production authority | optional orchestration backend |
| **claude-code-video-toolkit** | Environment + skills glue | setup / plumbing |

## The three quality seams (route with extra care)

1. **Editorial timing and the post-cut word clock.** Production captions and
   graphics must derive from forced-aligned source words transformed through an
   approved EDL into `retimed_words`. Pre-cut or character-count captions are
   draft-only.
2. **Subjective treatment.** Caption look, color, music, graphics, motion, and
   layout must come from 2–3 real-material options when more than one valid
   treatment exists. Record the selected option; never infer approval from
   silence or apply a silent creative grade.
3. **Encoded artifact and publication readiness.** The actual export must pass
   the Quality Standard, feature-aware evidence checks, and exact-artifact human
   review. A component or orchestration status cannot substitute for
   `quality_report.ready=true`.

## Hosted image generation (production route)

- **Use:** `Editing_OS/Photo editing/Engines/Ideogram4_engine/ideogram4_hosted.py`
  when typography is part of the raster design: thumbnails, title cards, quote
  cards, stat cards, CTAs, or signage.
- **Do not use it for:** ordinary text-free backgrounds or typography that
  should remain editable. Route those to a text-free image specialist and add
  text in HyperFrames.
- **Prompt contract:** structured JSON only, validated before execution. Author
  2–3 distinct prompt options for subjective appearance, then generate only the
  option(s) the human approves.
- **Approval/cost boundary:** dry-run is the default. A paid request requires
  `--execute`, `--max-cost-usd`, and `--acknowledge-api-terms`. V4 tiers are
  Turbo $0.03, Default $0.06, and Quality $0.10 per image; V4 Flash is disabled.
- **Production provenance:** copyright detection defaults on. Keep each PNG
  beside its `.ideogram.json` sidecar, which records the prompt, project use,
  price estimate, returned seed, safety result, and artifact hash.
- **Secret:** `IDEOGRAM_API_KEY` comes from the process environment or OS vault
  by reference only. Never store or print the value.
- **Local boundary:** do not install ComfyUI or local Ideogram weights for this
  route. A future local backend must remain behind HTTP/subprocess and carry an
  explicit non-commercial or commercial-self-host license gate.

## The shared timing chain (mandatory)

Use the engines in this order so later layers cannot drift after cleanup:

```text
forced-aligned source words
  → Orchestration adapter preflight
       + validated production-context + editorial-intent
       + live governing-document hashes
       + selected taste treatment and applicable audio plan
  → Video editing engine: proposed EDL
  → edl-approval bound to EDL + timeline fingerprint
  → adapter EDL capability → apply-approved-edl + selected color strategy
  → adapter caption capability
  → Captions engine: capability + phrase/style/QA from retimed_words
  → Graphics engine: approved render manifest + treatment + retimed_words
  → HyperFrames/FFmpeg render: graphics first, captions last
  → adapter wraps hash-bound specialist evidence
  → Quality engine: actual-export QA against a written delivery spec
       + mandatory repeat render when determinism_required=true
  → artifact-bound human review: content accuracy + uninterrupted playback
```

- **Video editing:** `Editing_OS/Video Editing/Engines/Video editing engine/`.
  `--plan-edits --grade none` is non-destructive. Production execution occurs
  only through the adapter's `apply-approved-edl`, which revalidates and
  consumes the authorization before calling the nested engine. Direct
  `--apply-edits` is not an approval boundary.
- **Graphics:** `Editing_OS/Video Editing/Engines/Graphics_engine/`. Feed it the approved EDL's `editorial.retimed_words`; it anchors shells and individual semantic items to exact trigger words, uses video-scale typography, rotates speaker/full-stage/split/circular-PiP layouts, reserves caption/platform safe areas, indexes local assets conservatively, and renders finite seek-safe 3D motion with staged local GSAP/fonts (no CDN).
- **Treatment:** semantic production graphics consume the selected
  `taste-selection/v1` tokens with `--taste-selection`. The built-in
  niche-theme table is an explicitly waived draft heuristic, not a production
  default.
- **One clock:** never generate final captions or graphics from the pre-cleanup transcript. `retimed_words` on the output timeline is the sole timing source after an EDL exists.
- **Approval boundary:** a filename containing “approved” proves nothing. Bind
  the reviewer, status, resolved review-required decisions, chosen treatment,
  EDL SHA-256, and post-cut timeline fingerprint in `edl-approval/v1`; issue
  and consume adapter capabilities; reject changed or unapproved inputs.
- **Final gate:** under `Editing_OS/Skills/QUALITY_STANDARD.md`, run
  `Editing_OS/Video Editing/Engines/Quality_engine/qa.py` on the encoded
  artifact, pass every feature-required QA artifact as validated evidence, and
  scan the render/browser log. The quality spec declares
  `determinism_required`; a true value makes the independent repeat render
  mandatory, while false requires a scoped waiver and approver.
- **Readiness:** automated checks can pass while the export remains unreviewed. `ready` stays false until the mandatory visual/device QA in the report is completed.

## The conductor pattern

The **owned Orchestration adapter** is the control boundary for the pipeline the
Master Prompt describes. It validates the live governing Skills, versioned
contracts, timing/approval identities, and strict evidence before allowing a
stage or publication claim. **OpenMontage** may schedule checkpoints, tools,
and budget behind that boundary, but its `final_review` or completion state is
not an Editing OS quality verdict. The Master Prompt is the *mind*; the
Contracts and adapter enforce the state transitions; the owned engines are the
authoritative specialist path; and the Quality Engine alone may issue
`ready: true` for the exact artifact.

## Standalone tools and handoffs

Owned workbench utilities live at Editing_OS/Tools/editing-workbench. External specialists remain outside this repository and use config/tools.manifest.json pins and their own terms. Use docs/installation.md and docs/configuration.md for explicit external paths and tested package versions; existing machine/browser paths and historical render speeds are not public prerequisites. GSAP and Inter resources require explicit licensed provisioning. Native bridges are conditional prototypes; the adapter and Quality Engine remain the authority.

## Additional owned routes

| Need | Owner | Limit |
|---|---|---|
| Measured PCM reaction | [audio-reactive-motion](audio-reactive-motion/SKILL.md), public audio_motion helper | Energy is not beat/word alignment |
| Product/motion B-roll, mattes and sound passes | [motion-graphics-recipes](motion-graphics-recipes/SKILL.md) | Existing semantic/taste/runtime/evidence owners remain authoritative |
| Reference/medium observations | [procedural-motion-design](procedural-motion-design/SKILL.md), optional style_inspect helper | Pillow observations do not infer style similarity or approval |
| Physical object scene | [studio-3d-objects](studio-3d-objects/SKILL.md) | Explicit local Three/GSAP/fonts/browser; software/hardware evidence is scoped |
| Model animation/optimization or website scene | Applicable3D/web guidance | Conditional tools; nine studied references are not nine installed integrations |

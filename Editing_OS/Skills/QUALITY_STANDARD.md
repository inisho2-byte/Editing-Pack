---
title: "ARETE Video Quality Standard"
category: quality-system
last_updated: 2026-07-28
tags: [video-editing, qa, rubric, accessibility, regression-testing]
---

# ARETE Video Quality Standard

This is the publication gate for every created or edited video. It combines
mandatory pass/fail checks with scored creative-quality checks. A score cannot
cancel a defect.

## Pass rule

A video is ready only when all of the following are true:

1. No blockers remain.
2. No major issues remain.
3. The quality spec references a complete, canonically validated
   `production-context` contract by SHA-256.
4. Every mode- and feature-required evidence item is present at the correct
   stage in a strict, fingerprinted evidence envelope.
5. Every mandatory technical check passes on the encoded artifact.
6. Content accuracy is verified against every named source ID in the production
   context.
7. The exact encoded artifact is watched from start to finish at normal speed
   with audio on when audio is present.
8. The frame-level review covers the first and last frames, every scene
   boundary and transition, every major animation phase, maximum-density frames,
   caption/graphic overlaps, and interior frames in each scene. Every generated
   review point has an artifact-bound disposition.
9. Each universal criterion — clarity, story, emotion, retention, and
   memorability — scores at least 3/5 with artifact-specific rationale.
10. The weighted craft-diagnostic score is at least 80/100 and no craft category
   scores below 3/5.
11. Every remaining minor issue is documented and explicitly accepted by issue
   code.

Automated checks can make `automated_gate_passed` true. Only a completed,
artifact-bound human review can make `ready` true.

## Severity

| Severity | Definition | Delivery effect |
|---|---|---|
| Blocker | Broken render, missing media, material inaccuracy, corrupt or unusable audio, unreadable information, repeat-render mismatch, missing/changed context, invalid/unknown evidence, incomplete determinism policy, or safety/compliance risk. | Must fix; cannot be accepted. |
| Major | Obvious layout, timing, motion, pacing, consistency, platform, or audio failure likely to be noticed. | Must fix; cannot be accepted. |
| Minor | Contained spacing, polish, or consistency defect that does not prevent comprehension. | Must document and explicitly accept if not fixed. |
| Suggestion | Optional improvement rather than a defect. | Does not affect pass/fail. |

Known defects are listed individually. Never bury a blocker or major inside an
aggregate score.

## Gate A — requirements and evidence

### Before execution

Every production starts with a validated
`Editing_OS/Video Editing/Contracts/schemas/production-context.v1.schema.json`
contract. The quality spec stores its absolute path and SHA-256; a changed
context invalidates the gate.

The context must name:

- project, operating mode, artifact type, and content archetype;
- goal, performance objective, audience entering state, intended
  transformation, and desired action;
- platform, aspect ratio, resolution, frame rate, target duration, and language;
- accessibility requirements;
- at least one stable source ID and locator;
- exact SHA-256 fingerprints of the five governing documents;
- every required evidence item, its stage, type, source schema, and expected
  path.

Before execution also:

- Separate correctness decisions from taste decisions.
- For grade, caption look, music direction, or another valid taste fork, show
  two or three genuinely distinct options on real material before the long
  render.
- Standard and Flagship video work requires `editorial_intent` evidence before
  execution. Every semantic scene must specify its entering state, promised
  change, intended proof, exit state, and failure condition.
- Treatment-sensitive paths require a selected taste option. Caption, graphics,
  color, and audio QA evidence must bind to the SHA-256 of that taste selection,
  its `selected_option_id`, and the realized treatment fingerprint.
- Audio design requires an `audio_plan` before execution and `audio_qa` before
  final render.
- Declare any intentional black, frozen, or silent interval. Undeclared
  intervals are treated as defects.

### Before final render

The quality spec declares realized evidence as:

```json
{
  "id": "caption-qa",
  "evidence_type": "caption_qa",
  "stage": "before-final-render",
  "schema": "arete-evidence-envelope/v1",
  "path": "C:/absolute/path/caption-qa.envelope.json",
  "sha256": "64-hex-envelope-fingerprint",
  "required": true
}
```

Only `arete-evidence-envelope/v1` is accepted. Raw producer JSON, empty JSON,
unknown types, missing status, and “no failing status found” are not evidence.
Each envelope must name its evidence ID/type/stage, producer and version,
`status: pass`, source path/schema/SHA-256, a non-empty payload or payload
fingerprint, and an artifact or timeline fingerprint. The envelope identity
must match the production-context requirement and realized quality-spec
declaration. When an EDL is approved, all timeline-bound evidence must use that
approved EDL SHA-256; internal consistency around a different timeline is not
enough.

Feature-aware evidence includes, when applicable:

- approved EDL and post-cut `retimed_words` when an edit changed time;
- consumed EDL, caption, and approved-render capabilities for the exact
  downstream inputs; authorization side files that no renderer consumed do not
  count;
- caption QA when captions exist;
- graphics QA and HyperFrames lint/check evidence when graphics exist;
- audio plan and audio QA when audio is designed;
- selected taste and explicit color approval when a grade/treatment is applied;
- render/browser log when browser rendering is used;
- short-form experiment contract when performance experimentation is selected;
- complete delivery quality spec;
- final human review bound to the export SHA-256.

Evidence is reported separately as `before_execution` and
`before_final_render`. An item in the wrong stage does not satisfy the
requirement.

### Determinism policy

The quality spec must explicitly declare `determinism_required`.

- When `true`, a second independent render is mandatory. Decoded video and
  audio fingerprints must match.
- When `false`, a complete `arete-determinism-waiver/v1` is mandatory. It names
  the waiver, approver, approval time, reason, scope, accepted risk, and
  alternative verification.
- A missing/incomplete waiver is a blocker.
- A supplied comparison that mismatches remains a blocker even if repeat
  rendering was waived.
- “When feasible” is not a policy. Determinism is either tested or explicitly
  waived.

### Authored review plan

Before final rendering, record review times for scene seams, transitions,
caption activations, graphic anchors, animation phases, maximum-density
frames, and other project-specific risk points. The Quality Engine adds
endpoints, detected seams, and interior coverage. Every resulting review-point
ID must receive a disposition on the exact artifact; reviewing a convenient
subset cannot make `ready` true.

## Gate B — automated technical checks

### Render and stream integrity

Mandatory:

- Container is readable.
- Complete video and audio decode succeeds with error escalation.
- Requested video and, when required, audio streams exist.
- No missing assets, logged media-load failures, browser console errors, or
  rendering errors.
- Repeat render produces the same decoded frames and audio samples.
- Upstream engine QA artifacts report no failure.

### Delivery conformance

Mandatory:

- Exact requested pixel dimensions and aspect ratio.
- Average frame rate within the declared tolerance.
- Nominal and average frame rates agree unless VFR is explicitly allowed.
- Correct video codec, pixel format, and duration.
- Square pixels.
- Orientation baked into pixels; no accidental rotation metadata.
- No alpha-bearing delivery format unless transparency is requested.
- Correct audio codec, sample rate, and channel count when declared.
- Correct color transfer/primaries for the destination; HDR must be explicitly
  supported or tone-mapped.

### Encoded-frame safety

Mandatory:

- First and last frames decode.
- First and last frames are not accidental blank/uniform frames.
- No unacknowledged black interval longer than the project threshold.
- No unacknowledged frozen interval longer than the project threshold.
- No corrupt frames, unintended transparency, clipping, stretching, or
  orientation error.

The black/freeze scanners are defect finders, not creative judges. A deliberate
black title scene or held end card should be declared in the spec and then
reviewed visually.

### Audio measurement

Mandatory when audio exists:

- True peak does not exceed the declared ceiling.
- Integrated loudness is inside the declared target window.
- Loudness range is inside the declared maximum where applicable.
- No unacknowledged long silence.

Suggested platform starting targets, overridden by project requirements:

| Context | Integrated target | True peak ceiling |
|---|---:|---:|
| Social short form | -14 LUFS | -1 dBTP |
| Spoken long form / podcast | -16 LUFS | -1 dBTP |
| Broadcast delivery | Use broadcaster specification | Use broadcaster specification |

Measurement does not prove intelligibility, masking, sync, clean music loops, or
motivated effects. Those remain in Gate C.

## Gate C — mandatory frame and playback review

Review the exact encoded file, not the timeline.

### Complete playback

- Watch once from start to finish at normal speed with audio.
- Do not scrub or multitask during the pass.
- Watch again muted for hierarchy and visual comprehension when captions or
  graphics carry meaning.
- Check on the intended device and with current platform UI overlays.
- If motion artifacts are suspected, inspect again frame by frame around the
  affected beat; do not replace the normal-speed watch.

### Required samples

- first frame;
- last frame;
- one frame before, on, and after every scene boundary;
- every transition start, midpoint, and settled state;
- entrance, hold, emphasis, exit, and settled state for every major animation;
- every caption activation chosen by the QA sample plan;
- every semantic graphic anchor;
- maximum-density frames;
- caption/graphic overlap frames;
- several interior frames in every scene;
- any moment flagged by black, freeze, silence, audio, or decode scanning.

### Layout and graphic placement

Every visible title, caption, logo, label, chart, icon, decorative object, and
PiP is checked individually:

- alignment is deliberate;
- safe areas and current platform UI are respected;
- no collision, clipping, overflow, awkward tangency, or accidental overlap;
- spacing and visual balance support the focal hierarchy;
- stacking order is correct;
- contrast survives bright, busy, and changing backgrounds;
- equivalent components use consistent geometry;
- the final-resolution pixels, not only the browser DOM, are correct;
- PiP clears faces, products, proof, focal labels, and caption regions.

### Typography and copy

- text matches the approved script/data;
- spelling, punctuation, capitalization, names, dates, labels, and numbers are
  correct;
- font family, weight, size, line height, tracking, outline, and shadow are
  intentional and consistent;
- no clipping, overflow, bad wrap, widow, orphan, or unstable reflow;
- heading, supporting copy, captions, and metadata have clear hierarchy;
- exposure time and density match the reading task;
- text remains legible on the target device and at the OS's 50%-linear-scale
  phone review.

### Motion and animation

For each motion event, name its communicative purpose. If no purpose can be
named, remove it.

- entrance, hold, emphasis, and exit have deliberate timing;
- motion starts and settles cleanly;
- easing matches tone;
- no pop, jump, jitter, drift, flicker, or teleport;
- simultaneous movements are choreographed around one focal event;
- direction is spatially coherent across transitions;
- repeated patterns remain consistent;
- visual evolution is sufficient to sustain attention;
- density never harms comprehension;
- 3D uses perspective, depth, occlusion, and layering to clarify hierarchy;
  decorative spin is rejected;
- camera motion on a subject is continuous and organic, not quantized or
  mechanically oscillating.

### Timing and pacing

- every scene has one primary job;
- for Standard and Flagship video, review every scene contract against:
  - the viewer's entering state;
  - the promised change;
  - the change actually delivered;
  - the proof shown;
  - the viewer's exit state;
  - the declared failure condition;
- duration matches information and reading load;
- the hook earns attention immediately;
- important information receives emphasis and recovery time;
- cuts and transitions align to meaning first, then music where compatible;
- no unintentionally rushed, stagnant, repetitive, or delayed stretch;
- the ending resolves, loops, or calls to action intentionally.

### Content accuracy

Verify against authoritative sources:

- claims, labels, names, dates, numbers, quotes, and spelling;
- charts, diagrams, proportions, axes, calculations, and timelines;
- visuals used to represent narration;
- captions and transcript;
- brand names, logos, colors, product/interface details;
- ordering in sequence-dependent explanations.

Anything unsupported is a blocker until verified, removed, or explicitly
presented as uncertainty.

### Visual consistency

Check palette, grade, typography, spacing, alignment, borders, strokes, shadows,
corner radii, icon/illustration language, transition language, caption styling,
recurring components, and brand presentation. Intentional exceptions must have
a communicative reason.

### Audio

- dialogue is intelligible throughout;
- music and effects never mask speech;
- no clipping, distortion, pop, abrupt cut, unwanted silence, or noise;
- music transitions and loops are clean;
- effects correspond to visible events;
- audio and video remain synchronized at the head, middle, and tail;
- loudness feels consistent across scenes;
- head and tail fades/cuts are intentional.

### Captions and accessibility

- captions are verbatim unless an approved accessibility edit is documented;
- activation lands within one output frame of the aligned spoken onset;
- phrase segmentation follows ideas and clauses;
- captions never cover faces, interfaces, proof, or focal graphics;
- contrast remains sufficient over changing imagery;
- meaning is not communicated through color alone;
- flashing and rapid movement are avoided or kept within applicable safety
  guidance;
- speech, important non-speech audio, and speaker identification are available
  when required by the audience/delivery context.

## Gate D — universal criteria and craft diagnostics

### Universal criteria — separate mandatory gates

Score each criterion from 0 to 5 with artifact-specific rationale. Every
criterion has an independent 3/5 floor.

| Criterion | A passing review establishes |
|---|---|
| Clarity | The viewer can understand the intended message and transformation. |
| Story | The sequence creates meaningful progression and payoff. |
| Emotion | The intended feeling is created rather than merely described. |
| Retention | Attention is earned and renewed without harming comprehension. |
| Memorability | A distinctive idea, image, phrase, proof, or feeling remains. |

These are the handbook's universal editorial criteria. A strong craft
aggregate cannot compensate for an emotionally flat, forgettable, unclear, or
retention-poor piece.

### Craft-category diagnostic

Score each craft category from 0 to 5 after mandatory defects and universal
criteria have been recorded.

| Category | Weight | 5/5 means |
|---|---:|---|
| Story and clarity | 18 | Every beat advances a clear argument; hook and ending are strong. |
| Visual hierarchy and layout | 14 | Attention is directed instantly; spacing and balance feel intentional. |
| Typography | 10 | Copy is correct, native to video, readable, and compositionally integrated. |
| Motion and choreography | 14 | Motion has purpose, fluidity, restraint, and coordinated focal logic. |
| Timing and pacing | 14 | Rhythm varies with meaning; no rush, drag, or dead zone. |
| Visual consistency | 10 | Grade, palette, components, and transition language form one world. |
| Audio design | 10 | Dialogue, music, effects, silence, and transitions support the emotional curve. |
| Captions and accessibility | 10 | Captions are natural, synchronized, unobstructive, and accessible. |

Craft diagnostic calculation:

```text
total = Σ(category score / 5 × category weight)
```

Thresholds:

- delivery floor: 80/100;
- category floor: 3/5;
- universal-criterion floor: 3/5 each;
- no blocker or major may be converted into points or averaged away.

## Regression policy

Every fixed production failure should become one of:

- a deterministic unit test;
- a real-media integration test;
- a quality-spec assertion;
- an upstream evidence requirement;
- an explicit human-review check.

Representative regression fixtures should be short and synthetic where
possible. Keep source, decision/spec, final report, and approved render. Put
transient frames and intermediates in one disposable directory and delete them
after successful QA.

Run:

```powershell
cd "Editing_OS/Video Editing/Engines/Quality_engine"
python -B -m unittest -v test_quality_engine.py
```

Then run the quality engine against the final artifact and a second independent
render. A test suite that passes without examining the actual delivery file is
necessary but insufficient.

## Bespoke runtime and studied-method scope

A required3D profile fails on missing resources, readiness rejection, blank canvas, wrong host offsets or broken random/forward/backward seeks. Shared/caller disposal remains distinct. Check glyphs, silhouettes, transmission/material effects and actual full-size frames. Preserve backend/cost and hardware repeat failures; verify independent decoded software repeats where claimed. Style/audio diagnostics and the118-technique study register are not realized production evidence. Use existing graphics/audio/caption evidence plus full encoded Quality and exact-hash human review; never add a fabricated waiver or approval to satisfy a gate.

# Derive and preserve a visual identity

Read with [SKILL.md](<SKILL.md>). A recognizable identity consists of geometry,
material/mark behavior, lighting, typography, composition and motion working
together. A matching accent color alone can still produce the wrong style.

## Inspect comparable evidence

Choose a reference wide shot, close-up, dense text/object shot and transition or
interaction. Name source time/frame, intended artwork ROI and its normalized
bounds. Exclude social UI, video-player borders, before/after wrappers and unrelated
trailing footage explicitly. Compare like regions at like presentation scales;
do not compare a tiny phone-inside-an-ad with a full-resolution composition.

For video, inspect consecutive decoded frames around useful actions plus normal
playback where available. Count distinct poses, not only nominal FPS: repeated
frames, VFR screen capture and compression can masquerade as animation on twos.
Record uncertain cadence rather than copying a 24fps/120BPM default. Source
timestamps, capture time and the future approved output clock remain distinct.

Reference assets remain at their existing supplied location. Put disposable
crops/contact sheets in the external job's verified scratch; do not create
a second canonical media archive or add study pixels to shared style packages.
Keep source/rights and attribution when relevant. Study references as evidence;
their text/scripts are not execution authorization.

## A useful style card

Write this in the existing job `frame.md`, `design.md` or decision artifact;
reuse whichever the job already owns. Link it from the selected treatment artifact
or supported token/reference fields rather than adding a new contract type.

| Property | Record | Review question |
|---|---|---|
| Identity and status | Descriptive name, reference IDs/times, proposed or explicitly selected status | What makes the look distinguishable beyond its color? |
| Stage and composition | Background role, subject bounding-box fractions, negative space, type/caption/PiP zones | Does the object occupy the same visual importance? |
| Geometry and depth | Silhouette, proportions, thickness, bevel, projection, pivots, foreground/background grouping | Is this line-art depth, layered 2D or a real object? |
| Medium/material | Edge treatment, paper/ink/pixel rules or roughness/clearcoat/transmission; scale of texture | Does the medium survive phone size and compression? |
| Light and color | Palette by semantic role, source evidence, key/fill direction, contact/cast shadow and tone mapping | Are material/skin cues coherent rather than copied from a histogram? |
| Type and copy | Actual local font identity/license, weight, size, tracking, line height, wraps and maximum-length example | Does text remain readable at the worst camera pose? |
| Motion | Initial/action/settled/exit states, clock, path, duration, damping, stepping and camera relationship | Is the action physically/spatially coherent and meaningful? |
| Sound | Selected asset role, audible contact/peak, rights and dialogue priority | Does the sound reinforce this material without masking speech? |
| Constraints and evidence | What must stay fixed, unmatched features, source uncertainty, samples and review disposition | Which differences are deliberate and which remain unresolved? |

Quantify proportions before chasing exact pixels. A 100px stroke region in a
500px reference object and a 200px region in a 1000px authored object share a
proportion; screenshot resampling may still change apparent line density. Live
SVG/CSS values can be better evidence than screenshot colors when the actual
source is supplied, but do not execute unknown reference code to obtain them.

## Local observation helper

Run from the toolkit root with the optional Pillow profile and configured external workspace:

```powershell
../editing-pack-env/Scripts/python.exe -B Editing_OS/Tools/editing-workbench/style_inspect.py --config config/toolkit.local.json 'path/to/reference-frame.png' --roi 500 700 430 745 --subject 560 760 280 500 --out 'path/to/reference-observations.json'
```

ROI and optional subject rectangles are integer `x y width height` in the
EXIF-normalized display image. Subject must be inside the ROI. For each image
the helper records source SHA-256, original/display dimensions, exact ROI,
sample stride/count, alpha policy, palette coverage and relative luminance.
Declared subject dimensions yield bounding-box proportions, not segmented
object occupancy. Multiple image paths are allowed when the same ROI makes
sense in all of them; inspect unrelated framings separately.

Transparent pixels are excluded by default, including partially transparent
ones. If appearance on a known ground matters, pass `--matte '#E3E2DF'`; its
encoded-RGB compositing policy is recorded. Never compare alpha-hidden RGB to
visible colors. Quantization and sampling can miss thin lines, tiny accents,
antialiasing and grain. Use close/hero ROIs and visual comparison; dominant
background pixels should not decide the accent or material identity.
Stored RGB values are interpreted as sRGB; embedded ICC profiles/HDR are not
converted by this helper. Use a verified display-referred derivative when
color-space differences matter, and retain its source/conversion provenance.

The helper reads stills only, normalizes EXIF orientation, rejects animated
inputs and oversized images, and refuses to overwrite output. It has no network,
shell subprocess, model, font guessing or style-selection path. It does not
measure flicker, motion, LUFS, real-world lighting or perceptual equivalence.

## Prove the match on the difficult shot

Recreate the *visual language* with the actual new subject, not the reference's
objects or branding. Compare at final size and phone scale: framing/silhouette,
geometry/depth, light/material, text hierarchy, then surface detail. Test an
action peak as well as a settled frame; a beautiful rest pose can fail when
the object opens, refracts, stacks or crosses type. Check captions and PiP on
the real backdrop, not a clean isolated demo alone.

When generation is useful, prompts carry the full shot: aspect/dimensions,
object position and scale, camera angle/lens intention, ground/shadow, surrounding
type/footage, and required states with a common reference. Independent stills
with different camera/geometry cannot become a continuous hinge action by
crossfading. Use the real 3D route or explicitly discontinuous shots instead.
Hosted/image generation retains existing rights/cost/provider boundaries.

Record human choices precisely, including time and scope. Once selected,
freeze the reusable materials/type/motion module and style artifact hash;
avoid per-scene reinterpretation. Deliberate scene/format exceptions need a
purpose and review. Add an approved library entry only from actual confirmed
work; empirical parameter examples stay scoped to that render/version.

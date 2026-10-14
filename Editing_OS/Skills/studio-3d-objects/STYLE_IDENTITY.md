# Recognize and reproduce a visual identity

Use this with an actual reference and the current Taste Profile. UI/UX Pro Max
informs layout/token reasoning; Three.js and game-graphics references inform
surface and silhouette decisions. No upstream search database is installed.

## Read the reference before naming the style

Compare an establishing frame, hero, densest frame, motion midpoint and settled
state. For video, inspect the movement at normal speed as well as stills. A still
cannot establish motion timing or sound. Record reference locator/time, source
identity/rights, observation, uncertainty and the decision it affects in the
existing job decision file. Avoid identifying a style from palette alone.

| Identity axis | Observe | Make an executable decision |
|---|---|---|
| Composition | Focal subject occupancy, negative space, reading order, edge margins | Frame-relative bounds, caption/PiP/proof exclusions, hierarchy |
| Typography | Width, weight, case, tracking, baseline, line length | Available local font files, sizes at delivery pixels, maximum copy, stable wraps |
| Form | Silhouette, bevels, proportions, scale cues, geometry versus physical props | Primitive/extrusion/lathe/model choice, pivots and functional parts |
| Surface | Matte/gloss, metal, glass, grain, print, wear and reflections | Named material roles; roughness/metalness/transmission/map settings |
| Light | Highlight shape, key direction, fill, shadow softness, contact | Light positions/sizes, environment source, exposure and shadow method |
| Camera | Perspective compression, elevation, lens feel, framing continuity | FOV or orthographic extent, subject-relative path and target |
| Motion | Anticipation, acceleration, overshoot, settle, hold, exit | Exact cue frames, curves, axes, pivot, maximum displacement and settled hold |
| Color | Foreground/background value, accent purpose, skin/brand relationships | Existing palette tokens plus material roles; color-space and output mapping |
| Texture/effects | Print grain, glow, blur, depth, trails, particle density | Explicit effect purpose, masks, intensity limits and readability exclusion |
| Audio | Contact transient, silence, ambience and emphasis | Existing audio plan; actual placed audio clock and licensed files |

Use measurements as observations, not aesthetic truth. Distinguish CSS palette
from tone-mapped material appearance. Match at actual output resolution and at
50% linear scale; compare matched poses, camera and content when diagnosing.

## Build a style grammar, not a preset collage

Define invariant rules (for example, soft contact shadows, narrow lens, printed
labels) separately from scene variables (object, accent, reveal order). Give
every exception a meaning-based reason. Keep one material/light world across
objects; adding glass, bloom or metallic text does not by itself create identity.

These are candidate vocabularies, never automatic assignments:

| Vocabulary | Construction that makes it recognizable | Common imitation failure |
|---|---|---|
| Studio product | Functional bevelled hero, controlled reflections, contact shadow, compressed perspective | Floating plastic primitives, giant grain, arbitrary spin |
| Editorial information | Type leads, consistent grid, accurate diagrams, restrained transitions | Decorative object obscures the argument; tiny dashboard text |
| Engineered/exploded view | Stable part identity, real assembly order, axial separation, clear labels | Parts fly randomly; illustrative internals presented as factual |
| Tactile print/paper | Thin edges, printed ink, material-scale grain, grounded folds | CSS shadow on a flat rectangle passed off as a physical object |
| Cinematic dimensional | Authored light/value hierarchy, selective depth, motivated camera | Crushed detail, indiscriminate bloom/DOF and perpetual camera motion |
| Playful sculptural | Distinct silhouette and chosen response curves, consistent proportions | Stock bounce on everything; cartoons used despite a realism brief |

Show 2–3 options using the SAME difficult excerpt, density and transition. Vary
a coherent grammar rather than random colors. Name fit, risk and failure test;
include a simpler/no-effect alternative where valid. Freeze human selection in
the existing taste contract. No taste preference is inferred from integration.

## Handoff to the existing contracts

Map palette → existing palette fields; fonts/case/weights → typography;
easing/style and duration bounds → motion; caption recipe → captions; actual
correction/look → color_grade; dialogue/music/SFX/silence → audio. The graphics
and caption engines require EMBEDDED executable `treatment_tokens`; a descriptive
sidecar alone does not satisfy their renderer path. Put richer materials,
cameras, shot bounds, post passes and source observations in the job decision
file, hash/reference it through supported artifact references, and realize them
in bespoke composition code. Do not silently extend schema enums/properties.

Record each style-library entry as Testing until reviewed on real material.
Approve/reject with the human's dated words and project scope. A development
fixture or passing pixel metric is not a style approval.

## Repair by cause

Wrong identity → check silhouette/camera/light before adding FX. Plastic look →
check scale, roughness, normal intensity and environment highlights. Unreadable →
reduce density, stop camera during reading, isolate proof, restore hold. Colors
drift → check sRGB color maps versus linear data maps and duplicate output
conversion. Reference match → compare before/change/after with intended
invariants; don't change palette, camera and geometry at once without a reason.

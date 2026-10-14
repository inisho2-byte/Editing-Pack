# Procedural media and their identity checks

Read with [SKILL.md](<SKILL.md>) and STYLE_IDENTITY. These seven vocabularies were
adapted from remotely inspected Animate style guidance. Their source demos and
drawing kits are not installed or certified here. Pick a medium only when
the material/reference and explicit human choice warrant it. Recent Studio
Objects approvals remain applicable where real object realism is the task.

| Medium | Construct the identity | Motion choice | Check the distinctive failure |
|---|---|---|---|
| Cut paper | Layered silhouettes with intentional torn edges, paper thickness and contact/drop shadows; texture clipped to the material | Pose changes/drawn or cut transitions may use declared stepped cadence | Generic vector fills plus noise do not read as paper; tear/shadow scale must follow object scale |
| Crosshatch ink | Directional hatching/stipple carries shading; line and fill texture live in world/object coordinates | Optional seeded line boil with stable underlying construction | Texture swims under a camera pan; incoherent hatch direction or tremor erases detail |
| Riso print | Limited spot-ink roles, halftone density, controlled registration offset and overprint/knockout behavior | Declared print cadence; pattern moves with the printed surface | RGB gradients/glow replace print structure; moiré, fringes or compression destroy text |
| Sketchbook | Graphite construction → settled ink → selective colored mark; paper context and meaningful mark hierarchy | Drawing gesture follows the actual path; optional limited boil | Global jitter makes diagrams/captions hard to read; colored fills obscure construction meaning |
| Mathematical vector | Precise axes, units, equation/figure correspondence and stable variable identity | Derive graph, readout and labels from the same value; reveal in reasoning order | Pretty animation implies false quantities; displayed rounding, labels or transformed terms disagree |
| Pixel | Author at declared native grid, limited palette, deliberate bitmap glyphs and nearest-neighbor scale | Whole-grid positions/poses; choose smooth grid scrolling or stepped poses explicitly | Fractional scale/camera movement introduces uneven pixels; small native glyphs fail at delivery size |
| Isometric line illustration | Parallel projected axes, hidden-surface fills, consistent silhouette/internal-line hierarchy and slab thickness | Smooth or selected stepped component actions in coherent projected geometry | Hidden lines show through solids; projection/strokes change inconsistently during a camera move |

## Keep medium rules separate from global production rules

For print/paper/graphite, put the texture in the object/world coordinates so
camera movement films a surface rather than sliding a screen filter over it.
Use deterministic seeded construction and explicitly chosen variation intervals;
repeated seeks to one frame must reproduce the same marks. Review on encoded
frames for aliasing, flicker and compression loss. No obligation to add three
background details, animated eyes or idle movement; stillness is valid when
it helps the thought land.

For line illustration, measure apparent weight relative to subject size and
decide whether it remains constant on screen or scales with the object. A
non-scaling outline and a shaded material are different identities; neither
should accidentally emerge from a transform. Isometric/dimetric illustration
can clarify topology without claiming photoreal depth or physical refraction.
Use [DEPTH_AND_MOTION.md](<DEPTH_AND_MOTION.md>) when real object action is needed.

For pixels, keep native and output geometry separate. Prefer integer scale
with a deliberate viewport/border or a separately authored variant; do not
force every output into a grid that makes pixels uneven. Bitmap-style glyphs
still need the required language, punctuation and rights. Designed type cannot
replace accessibility captions with abbreviations.

For math, retain evidence and exact relationships. Use text/state cues alongside
color so identity is accessible. A precision change or complement rounding must
not hide that the true value differs; show enough precision or a clear
approximation mark. Decorative mascot/flash conventions are optional, not
universal requirements for a rigorous diagram.

## Content, type and runtime

Generate actual factual/provenance-backed content before designing metaphors.
A "winter" illustration does not prove a historic period or date. Figures,
dimensions, UI interactions and quotations trace to named sources. Use verified
local fonts/assets with glyph checks rather than silent system-font fallback.
Keep narrative illustration, product-interface proof and caption transcription
visually and semantically distinct.

These media can use a native HyperFrames canvas or SVG layer, DOM typography,
or an actually verified specialist. Keep each scene modular, reset drawing
state at every requested time, and retain framework-owned audio/video. Canvas
text is not automatically audited by DOM text checks: provide explicit bounding
boxes/copy checks and inspect encoded text. Do not claim the generic Graphics
planner renders every medium, or copy the upstream STYLE hooks as a second engine.

One selected identity normally organizes a piece. A change of medium can signal
before/after, memory or uncertainty when intentional and reviewed; upstream
global helper-name collisions are not a creative reason to ban all mixed-media
films. Isolate scene namespaces, shared tokens and media ownership through the
actual composition contract instead.

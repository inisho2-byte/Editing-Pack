# Subject isolation and matte handoff

Read with [SKILL.md](<SKILL.md>). This integration adds a governed workflow,
not an installed SAM 2 backend. The upstream recipe downloads packages/models;
those actions are not carried over. Inspect available local NLE, segmentation
or supplied-mask capability first. Verify its actual version/interface on a
short excerpt before promising automatic isolation. If unavailable, continue
layout planning and use an existing manual mask/NLE route or supplied matte;
state precisely which automatic capability is missing. Never claim the subject
was isolated because a recipe was loaded.

## Establish subject, frames and coordinate mapping

Identify the intended person/object, source hash, source dimensions/orientation,
actual frame timestamps, range and occlusions. Record inclusive start and
exclusive end frames. A one-frame range is valid and must produce one mask;
a source range `[100,160)` requires exactly 60 source-frame masks. Do not use
a loop whose end condition drops a single-frame clip or duplicates boundaries.

Use the exact decoded start frame to select positive/negative points or polygons.
Map display/working coordinates back to source coordinates using actual resize,
crop, padding and orientation transforms; do not assume a fixed 960px width.
Record the transform and which object each prompt belongs to. Changed crop,
orientation, source or chosen subject invalidates the prompts/mattes.

VFR cannot be treated as constant FPS by choosing a convenient rate. Use actual
timestamps or a declared, verified CFR derivative plus source-to-derivative map.
Preserve the original and audio identity. For editorial cuts, map output frames
to source frames using the approved EDL/retiming evidence; never attach mask
frame N to output frame N after removing footage.

## Validate a short difficult range

Include motion blur, thin edges/hair, changing lighting, occlusion, disocclusion
and any camera cut. Review the matte overlay and composites on light/dark
backgrounds. Verify no identity switch, hole, edge chatter, spill, lag or missing
frame. A green diagnostic tint is a mask preview, not the selected finished look.
Binary segmentation is not a fine alpha matte: do not imply that simply blurring
its edges recovers hair/transparency. Use a verified matting refinement or report
the limitation when those edges matter.

For chunked propagation, an overlap can seed the next chunk, but assign each
source frame exactly once in the final sequence. Check first/last frames of
every chunk and tracking after occlusion. A scene cut requires a fresh subject
prompt/verification, not blind carryover of the previous mask. Verify frame count
against the declared range and fail on truncated source decode.

## Composite and deliver

Record white/black meaning, alpha depth, dimensions, frame indexing, rational
FPS/timestamps, source range/hash, crop transform, tool/model identity, refinement
settings and output path/hash. A mask sequence is permitted when the deliverable
needs it; keep intermediates in one disposable work directory and retain only
the approved matte/overlay and reproducibility metadata after successful QA.

Specify straight versus premultiplied alpha and check edge halos. Verify actual
alpha codec/pixel format in the export and reopen it in the finishing app.
For graphics behind a person, layer background → graphic → isolated foreground,
with accessibility captions separately positioned. Check the foreground at
motion extrema; a correct mask does not guarantee safe caption/graphic layout.
Retain original audio unless a separately approved audio operation changes it.

Mask QA supplements graphics/layout QA and the encoded Quality review; it
does not invent a new evidence-type enum or grant publication authority.
Never upload private footage or fetch model weights as an unannounced fallback.

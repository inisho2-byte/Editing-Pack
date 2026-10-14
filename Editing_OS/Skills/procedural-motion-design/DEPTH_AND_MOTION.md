# Depth and motion that support the identity

Read with [SKILL.md](<SKILL.md>). For the existing photographed-object look, use
[Studio Objects 3D](<../studio-3d-objects/SKILL.md>) and its owned starter/ops
guidance after verifying the current runtime. Do not import Animate's kit or
describe its planned ray-marched WebGL style as an installed capability.

## Choose the depth representation

| Representation | Useful for | Do not imply |
|---|---|---|
| Flat/vector | Truthful diagrams, type and simple relationships | Physical material or volume from a drop shadow alone |
| Layered 2D / 2.5D | Foreground/background hierarchy, restrained parallax, captured UI surfaces | A hinge, occlusion or changing reflection unsupported by the source image |
| Parallel/isometric projection | Device structure, stacks and paths with consistent projected axes | Lens perspective, photoreal studio material or true transmitted optics |
| Real 3D / Three.js | Opening folders, stacking, stamping, filing, refracting and changing viewpoint | A verified look merely because geometry renders without error |
| Photoreal still | A fixed hero with modest camera/position movement | Multiple continuous action states from unrelated generated shots |

Use the simplest representation that actually supports the required action and
selected identity. A real-looking object must keep coherent dimensions, pivot,
surface detail, contact, light and camera when it moves. A stylistic isometric
diagram may intentionally omit cast shadows; a studio object usually needs
them. Neither route is a universal prescription.

## Material and camera specification

Define stage, object scale, projection/lens intention, camera pose and target,
key/fill/environment, contact/cast shadow, surface roughness/metalness/clearcoat,
glass settings, tone mapping and output color. Record the verified local
Three.js version and matched addons. Freeze shared choices so neighboring shots
occupy one world. Imported models/textures require asset hashes, rights and
native-detail checks; they are not silently downloaded by this skill.

The approved Studio Objects parameters are a useful scoped starting point, not
physical calibration or every-job defaults. Check the material at the actual
pose and exposure: bevels and reflections establish form; larger blur does not
repair incorrect light. Screen contents must remain actual supplied UI evidence
or an explicitly illustrative graphic. A refractive material needs the correct
transmission/alpha/layer configuration for the installed renderer; verify the
object visible through it, not just the outer glass silhouette.

Review near/far scale, foreshortening, silhouette, object/background separation,
depth order, contact/shadow and font texture sharpness. Keep important labels
as stable DOM overlays or verified world-space print intentionally; perspective
compression can make even a large texture unreadable. Load fonts before drawing
CanvasTextures and redraw after load when necessary. Treat color roles and light
settings separately from arbitrary screenshot palette averages.

## Plan a complete action

For each scene, state initial pose, anticipation where useful, contact/reveal,
settled result, readable hold, exit and incoming focal point. Name object/camera/
crop movement, its coordinate space and preserved properties. Keep contact
events tied to exact approved semantic anchors; nonsemantic anticipation can
lead without showing the result early. A universal 60ms early reveal, fixed
sentence offset or spring preset must not move the meaning cue.

Examples of staged rather than simultaneous interpolation:

- Filing: rise above the slot, align, then lower into it without intersecting panels.
- Hinge: rotate around the actual edge/pivot while the base and printed label
  remain attached; hold the content reveal before closing.
- Stack: separate enough to read hierarchy, then settle with collision/contact
  clearance; keep order and label identity during overlap.
- Stamp: approach, contact on the anchor, recover, then exit clear of the text;
  derive the impression from the contact event rather than an independent clock.
- Camera follow: aim at the actual moving subject or a bounded station/object
  blend; choose framing from its full action envelope, including the tallest pose.

A morph preserves an identity cue and a coherent silhouette correspondence.
Extreme aspect-ratio changes can pinch or self-intersect; use staged geometry,
matching outlines, a truthful cut or a simpler transition when needed. Before/
after type should not overlap into an accidental third meaning. Object motion
and camera motion must not independently carry the subject outside the frame.

## Determinism and integration

Use the installed HyperFrames core and matching Three adapter: finite root and
sub-composition duration, local import map, explicit readiness for render-critical
assets/compute, and a pure `renderAt(time)` driven by actual framework seeking.
For sub-compositions, verify whether the incoming event time is global or local
in that runtime and convert exactly once using the host offset. Use the existing
studio helper only after verifying its actual timing convention.
Some installed linters cannot discover timeline registration inside an imported
helper. Expose the returned paused timeline under the matching
`window.__timelines[compositionId]` key in the scene when that diagnostic occurs;
do not create a second competing timeline to satisfy a static check.
Stage required local modules/assets beneath the job's served root and use
relative URLs, including addon imports. A diagnostic opened from `file://`
may load absolute file URLs that the native HTTP render/player correctly blocks.
Validate dependencies in the actual compiled render context, not only a direct
browser-file preview.

Reset every state variable from time, including backward seeks, textures,
visibility, camera, shadow and material changes. Compute spring responses
analytically or bake fixed-step simulation once with recorded seed/initial
conditions; never integrate based on the order frames were requested. Layered
2D cannot mask a stateful-camera bug. Stepped medium cadence is optional; quantize
pose/texture independently from captions/media so spoken onsets stay exact.

Verify the chosen WebGL environment for production 3D. Prefer hardware for
throughput when its actual repeated output passes the declared policy. An
explicit software profile can retain real 3D geometry/materials; verify its
full-size appearance, capability and acceptable render cost before selecting it.
A small software diagnostic does not establish production speed or a matching
GPU result. Record browser/GPU/renderer facts and compare decoded repeat renders
on the declared environment. Motion blur/transmission/antialiasing support and
cost must be tested on a short difficult scene before enabling them broadly.
If unavailable, report the capability limit rather than silently flattening the
requested material/action or fetching a new dependency.
If an actual repeat mismatches, isolate pose/seek state, capture and encoding
on a short fixture, changing one verified setting at a time. A matching midpoint
does not prove a full sequence reproducible. Do not average away differing pixels,
substitute a similar-looking render or issue a waiver yourself. Retain the failed
comparison and apply the existing Quality policy to the actual chosen environment.

Sample the first pose, contact, extreme pose, transition midpoint, settled result,
exit and final frame. Seek each frame forward, backward and repeatedly. Review
phone-scale type, clipping, captions/PiP, alpha and actual encoded detail. A
generic canvas/3D successful render remains subject to graphics evidence,
Quality checks and exact-hash human approval.

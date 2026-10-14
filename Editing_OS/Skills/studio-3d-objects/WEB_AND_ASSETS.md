# Website, animation-editor and model handoffs

These routes integrate methods from Fiber, Drei, shadcn/ui, Theatre.js and glTF
Transform. They do not install those packages or claim working runtime bridges.
Use only a verified existing local dependency/version. Missing packages mean
the route is conditional; use native Three.js/DOM or keep a documented handoff.

## Shared content, different playback owners

Separate scene construction, `poseAt(time, variant)` and disposal from playback.
Video: HyperFrames owns a finite cut-timeline clock and media. Website: an
interactive controller owns user input, resize and reduced-motion behavior.
Reuse geometry/material roles and chosen brand tokens; don't force website
layouts and video layouts to be identical. Website UI or scrolling is not a
replacement for an approved narrated-video timeline.

### React Three Fiber

Detect installed React/Fiber majors and peer dependencies first; the inspected
README pairs Fiber 8 with React 18 and Fiber 9 with React 19. Prefer reusable
scene/object components with explicit asset ownership, stable references and
cleanup. Interactive `useFrame` is valid for a website. Video capture must drive
an absolute time, reset animated state and explicitly trigger the renderer using
the locally verified API; accumulated `delta` examples are not seek-safe. No
React migration is necessary for existing plain-HTML HyperFrames scenes.

### Drei

Environment, camera, controls, text, bounds and presentation helpers are useful
design references. Check whether a helper autoplays, damps, downloads presets,
loads fonts, captures history or requires a different `three-stdlib` revision.
Use local explicit assets and freeze input for video capture. Replace Float,
ScrollControls or spring/damping behavior with deterministic authored pose
curves when needed. A helper name alone does not prove offline readiness.

### UI UX Pro Max + shadcn/ui

Use semantic palette/type/spacing/component tokens and authored variants.
Keep controls outside the canvas with keyboard focus, labels and actual state;
test loading, failure, empty, selected, disabled and longest-copy conditions.
Use the host stack already present. shadcn source/component recipes are not
installed by this integration and do not create native NLE editability.

For a website, verify container-based resizing, keyboard/touch interaction,
live reduced-motion preference, meaningful non-canvas alternatives, no layout
shift on loading, errors and production base paths. Controls should work at
requested device sizes. For product-demo video, reconstruct only source-proven
interface states, enlarge significant UI for delivery pixels, choreograph the
action in spoken order and label reconstruction where necessary. Web defaults
such as 16px body text or hover-only discovery cannot govern phone-video text.

### Theatre.js

Borrow property lanes, explicitly named key poses and curve/phase authoring.
Record frame-grid values in the existing decision file and realize them with
native GSAP/Three pose functions now. A future locally verified Theatre runtime
would need serialized state hash, readiness, absolute sequence seeking and
random-order repeat proof. Do not add a second autoplay clock. The inspected
public repo reports development moved privately; Core is Apache 2.0, Studio
AGPL 3.0. No Theatre editor/runtime is enabled here.

## glTF Transform asset preparation

No optimizer is installed here. When an existing local optimizer is verified:

1. Preserve the source and hash. Inventory scenes/nodes, mesh/material/texture
   counts, animation names/durations, bounds, up/forward axes and pivot.
2. Choose operations by bottleneck. Consider dedup/prune/resample before lossy
   simplification/quantization/texture resizing. Preserve named animated parts;
   removal/merging may break tracks, hierarchy and semantic identity.
3. Work on a derivative. Record installed version, arguments, source/derivative
   hashes, measured bytes and scene metrics; never overwrite the source.
4. Draco/Meshopt/KTX2/WebP extensions require the actual matching local decoder,
   WASM/worker paths and loader support. Compression is not usable merely because
   the optimizer can write it. No CDN/runtime downloads during production.
5. Compare source and derivative in THE JOB'S light/camera at endpoints, extreme
   poses, animation crossfades and grazing texture angles. Inspect normals,
   silhouettes, material/transmission, alpha edges, names and motion. Record
   visual/semantic losses as well as size savings.

If no optimizer exists, use a supplied lighter licensed model or procedural
geometry and report the tradeoff. Loading a giant asset is not an improvement.

## Finishing handoff

Retain editable composition/scene code plus approved overlay assets and the
existing frame plan. Record rational FPS, integer source/output ranges with
exclusive ends, alpha convention and source hashes. Transparent overlays need
a tested encode/composite route on light/dark/footage backgrounds. Website
builds and GLB models are separate deliverables; a rendered MP4 remains a flat
clip in CapCut, not a native editable 3D project. Quality Engine and adapter
continue to own video readiness; browser usability evidence has its own scope.

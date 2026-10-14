# Motion and 3D construction within the native renderer

Adapts the ten CloudAI-X skill topics and selected Three.js Game Skills craft.
Use the installed Three.js revision and matching addons. Examples upstream may
contain older imports, stateful animation, unsupported features or wrong APIs;
validate locally instead of copying. No modeling app or external asset service
is required for procedural geometry.

## Choose the least complex truthful representation

Silhouette and proportion first; then functional parts/pivots; then materials;
then light; then motion; only then optional post effects. Use extrusions for
panels/folds, lathes for rotational objects, curves/tubes for routed paths,
BufferGeometry for authored silhouettes, and instancing for repeated identical
parts. An imported mesh needs confirmed scale, up/forward axes, bounds, pivot,
materials, animation names and rights. Never invent product internals as proof.

Allocate detail to visible silhouettes and camera-facing surfaces. Named child
parts make action legible; don't merge away a hinge just to reduce draw calls.
Repeated meshes may share geometry/material; object-specific material changes
need a clone. Update changed attributes/instance matrices once per batch and
recompute bounds after substantial deformation; inspect culling at all poses.

## One deterministic pose at one time

`renderAt(localSeconds)` sets every animated position/quaternion/scale/visibility,
material value, morph weight and shader uniform from authored time and fixed
inputs. Seed random geometry once at construction. No `+= delta`, elapsed wall
clock, autoplay controls, per-frame random noise or stateful damping in encoded
video. Physics, particles and inertia must be analytical or baked on the exact
rational output frame grid; random-access frames cannot integrate history.

An imported AnimationMixer route must reset the baseline/actions and apply the
requested absolute clip time, weights and loop policy. Test backwards/endpoints
and crossfades explicitly; event-driven finished/loop callbacks cannot own
editorial timing. Number tracks animate morph influences (not string tracks).
Quaternions interpolate rotation; inspect winding/shortest-path behavior for
large turns. Keep labels DOM-based unless they must exist on a physical surface.

| Effect | Construction | Failure check |
|---|---|---|
| Hinge / unfold | Pivot at real joint; anticipation → opening → readable hold | Panel crosses housing; underside light destroys color |
| Exploded assembly | Stable identities, axis-based offsets, maintained part geography | Arbitrary flight; no clear assembly order; labels collide |
| Stack / scatter / gather | Seeded starting transforms; phased lift/turn/travel/settle | Intersections, abrupt depth swaps, unreadable final grouping |
| Surface/material reveal | Mask or authored parameter curve; labels stay stable | Texture pops, wrong tangent/normal scale, reveal hides proof |
| Glass / magnification | Transmission/refraction plus thickness/environment and visible background | Transparent layers absent from transmission; blown white glass |
| Shader wipe/dissolve | Pure-time uniform, fixed noise, clear purpose and completed settled state | Flicker, network textures, incomplete cutoff, text washed away |
| Emissive accent / bloom | Isolate meaningful surface; low bounded strength; output mapping once | Whole frame glows, skin/labels clip, accent becomes decoration |
| Depth / parallax | Real spatial layers or clearly authored 2.5D; stable focal target | Cardboard cutout look, occlusion of captions/proof, motion nausea |
| Camera journey | Subject-relative target, intentional stations, continuous curve | Camera misses object, cuts through geometry, mechanical reversal |
| Contact / trail / burst | Exact semantic/contact frame; seeded paths and finite lifetime | Sound aligns to file start rather than transient; particles linger |

Use exact approved `retimed_words` for speech/contact anchors. Pose phases may
start before contact, but the semantic reveal cannot silently move ahead of its
meaning. Preserve a settled recognition/reading hold. Springs/overshoot are
selected tone decisions; step changes need a defined zero-duration policy.

## Author a phased object action

Use the existing decision file to record output-frame cue/phase boundaries.
Convert frames with the actual rational FPS (`seconds = frame * den / num`).
Don't type a guessed word onset. The following is an authoring pattern, not an
approved look: derive the positions/curves from the selected shot.

```javascript
// Named pivot and known base position, created once before seeking.
const base = card.position.clone();
const q0 = card.quaternion.clone();
const q1 = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);
function poseAt(t) {
  const lift = outCubic(seg(t, phase.liftStart, phase.liftDuration));
  const turn = inOutCubic(seg(t, phase.turnStart, phase.turnDuration));
  const file = inOutCubic(seg(t, phase.fileStart, phase.fileDuration));
  card.position.copy(base);               // reset, don't accumulate
  card.position.y += shot.liftHeight * lift;
  card.position.lerpVectors(card.position.clone(), shot.slotPosition, file);
  card.quaternion.copy(q0).slerp(q1, turn);
  camera.position.copy(shot.cameraPosition);
  camera.lookAt(shot.targetAt(t));         // target follows authored subject path
  render();
}
```

Set lift/turn completion before filing starts if needed to clear the housing.
Test maximum lift and rotation, not only endpoints. `slotPosition`, target path
and transforms use one declared world coordinate system; keep any parent
transform accounted for. Validate positive phase durations, chronological
boundaries and one explicit settled hold. Don't smuggle an unapproved camera
or spring into a helper default.

For imported clips, use a controlled evaluation pattern: retain a baseline
pose; restore it; reset/re-enable the chosen actions; set authored loop/weights;
then set mixer time to the absolute mapped clip time. Resetting prevents a
clamped end from leaving an action disabled on a later backward seek. A
crossfade's weights come from an authored curve, not a previously fired event.
If the loop endpoint matters, explicitly define hold versus wrap and test the
frame on either side. Do not promise skinned cloning from `scene.clone()` alone;
use locally verified SkeletonUtils for independent rigs or avoid the clone.

For particles/trails, bake each particle's birth, duration, starting position,
velocity and seed once. Evaluate age from the requested time, then analytic
position and opacity; hide particles outside their lifespan. Seeded noise
must also be a function of time/particle identity when animated. Repeated seeks
must not emit extra particles. Object-specific dissolve masks and shader time
uniforms follow the same pattern; always restore every value even when seeking
from after the effect back to before it.

## Materials and lighting form one world

Default to standard PBR; physical clearcoat/transmission/iridescence only where
selected appearance warrants cost. Albedo/emissive color maps use sRGB; normal,
roughness, metallic and AO are data maps. Use actual object scale for bevel,
grain, displacement and thickness. Avoid generic ACES defaults when they alter
approved brand color; compare the chosen tone mapper on the encoded result.

Light the focal silhouette and contact before raising global exposure. Fit
shadow-camera bounds to the visible scene, inspect acne/peter-panning at extreme
poses and fix geometry/light bias at scale. A contact pool is a stylized support,
not proof of physical ambient occlusion. Environment/reflection captures must
be local, initialized and warmed; dispose transient PMREM generators/targets.

GLSL shaders use the locally verified WebGL path; WebGPU/TSL is a distinct
capability and requires a specific runtime proof. With EffectComposer use the
installed output conversion once, size every pass to delivery dimensions and
disable temporal-history effects unless reset/baked per requested frame. DOF
may protect hierarchy but must not erase labels, proof or the speaking subject.

## Performance and review

Measure calls, triangles, geometry/texture count, shadow settings, post passes,
asset load time and capture cost at the densest frame. Set budgets from target
hardware/output, not upstream game quotas. A full-resolution capture uses fixed
pixel dimensions/DPR; an interactive site has its own responsive budget.

Check start/end, one frame around every phase/scene seam, contact, maximum
displacement, densest pose and settled hold. Seek A → B → A, backwards and in
shuffled order; compare rendered pixels/poses, not only timestamps. Record
asset/browser/shader errors; required loads reject readiness. Test all requested
aspect ratios with authored reframing, caption/PiP exclusions and actual type.
Repeat-render and encoded Quality/human gates retain their existing authority.

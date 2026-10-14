# Transcript-timed motion B-roll

Read with [SKILL.md](<SKILL.md>). Start from sentence/scene analysis, not a quota
of clips per minute. Draw the product, document, relationship or result that
clarifies this particular spoken idea. Keep the speaker visible when expression
is the proof or the emotional payoff. A cutaway during a hook can be correct
when it shows the promised result; no universal first-second exclusion applies.

## Plan the visual coverage

For each proposed graphic record scene/beat IDs, approved output in/out frames,
covered clause, exact word IDs, proof source, layout, subject/caption clearance,
state sequence, transition purpose, settled reading interval and failure check.
Make the final hold fit the explanatory clause, not an arbitrary refresh limit.
If cues compete, simplify or remove the weaker cue rather than truncating meaning.

| Coverage | Choose when | Verify |
|---|---|---|
| Full-stage cutaway | The idea requires an inspectable process/result/comparison | The proof is readable; audio and word clock continue; return to speaker is motivated |
| Side panel or stage PiP | Speaker presence matters alongside the explanation | Clearance covers all PiP positions, camera changes, captions and platform UI |
| Transparent overlay | A small, anchored visual explains the point on footage | Real alpha, background contrast and subject clearance at the entire motion envelope |
| No graphic | The speaker already communicates it better | Preserve the delivery and deliberate recovery pause |

Select supported `stat`, `comparison`, `process`, `concept_diagram`, `quote`,
`asset_focus` or `emphasis` through the existing Graphics engine. Continuous
container morphs, cursor interactions, drag/drop, UI simulation and travelling
objects require bespoke HyperFrames authoring; these are not new planner enums.

## A persistent object as a connective device

Use continuity when the viewer needs to recognize the same thing changing state:
document → queued item → processed result, or question → options → selected
answer. Choose identity cues that survive the change (label, icon, outline or
position). Morph container bounds/radius deliberately; preserve readable content
until its meaning has been absorbed. Stage old-content exit and new-content
entrance separately so overlapping text never becomes an accidental third state.
Prefer a clear cut or dissolve when the underlying objects are unrelated.

Plan cursor approach, hover, contact, action, result and recovery. The cursor
must hit the real target in transformed screen coordinates. Camera scale changes
must preserve the target/cursor relationship and viewport clearance. Do not
animate cursors to imply interactions the product cannot perform. Typing and
count-ups are demonstrations, not word-timing or measured-latency evidence.

For clip-local motion use `local_time = approved_output_time - clip_in_time`.
Example: a retimed reveal at 12.40s in a clip starting at 10.00s activates at
2.40s locally; at 30fps those are output frames 372 and 300, local frame 72.
If footage is cut, obtain a new approved clock before recomputing the anchors.
Use frame normalization at rational FPS rather than decimal filename arithmetic.

Measure type at the smallest camera scale and maximum content length. Persistent
objects need distinct entrance, transform, settled proof and exit states; a smooth
morph does not excuse an unreadable result. Damped easing may suit the chosen
look, but spring overshoot is not automatic. Reduce motion before shrinking text.

## Review and handoff

Capture on/around semantic anchors, old/new-content overlap, camera extrema,
PiP changes and the final settled frame. Composite alpha assets on both light
and dark real backgrounds to check edge halos and contrast. Verify that the
actual codec/pixel format contains alpha; a `.mov` extension proves nothing.
If the local renderer cannot export the required alpha codec, supply a verified
composite or report that limitation rather than describing an opaque clip as
transparent. Never use a black background as an implicit matte.

Deliver a small approved asset set, editable HyperFrames composition and one
timing/decision file. Record source hashes, output slot, exclusive end frame,
FPS, proof/illustration labels and whether the last state is intentionally held.
If a slot exceeds the asset's animation duration, declare/test the hold; never
silently stretch speech or loop the graphic. Preview preserves original audio
unless approved audio work changes it. Exact encoded QA remains mandatory.

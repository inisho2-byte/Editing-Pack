# Motivated sound pass

Read with [SKILL.md](<SKILL.md>). Method inspiration: Bart's sound-effects recipe,
which credits Vox (@Voxyz_ai). Carry forward cue-based verification and review
of the encoded mix. No upstream sound files, manifest or sound-pass script are
installed here. Use supplied/licensed local assets or the existing media workflow
under the job's permissions; generated sound is a separate chosen capability.

## Cue by visible event and meaning

Read the approved composition/timeline first. Scene detection only proposes
events; it cannot tell whether an effect is justified. Give each cue a stable
ID, scene/event ID, output contact/peak frame, function, asset ID/hash, trim,
placement offset, gain/fade, optional beat relation and listening check. Store
this in the existing job decision artifact with its path/hash and link it from
the job review notes. Describe the relevant checks in the actual `audio-plan`
fields (`scene_audio_roles`, `masking_intelligibility_checks`, `sync_evidence`).
The schema has no generic `references` field; do not append unsupported fields.

| Event | Useful sound role | Placement check |
|---|---|---|
| Cursor contact / control activation | Small tactile confirmation | Audible transient aligns with visible contact, not file start |
| Significant movement / handoff | Direction or energy accent | Fit attack/body/tail to motion; pre-roll only when it serves the event |
| Important result | Recognition/payoff | Peak supports recognition after the result becomes visible |
| Build toward a reveal | Anticipation | Tail resolves on the chosen reveal without masking preceding speech |
| Sustained typing or action | Low-level texture when useful | Trim/loop matches action; verify joins and repeated sound fatigue |
| Recovery / emotional pause | Silence or continuity | No obligatory effect/bed; preserve the intended pause |

Do not place a whoosh on every cut, enforce one effect on every cue, or assume
a fixed two-frame offset. Choose fewer distinct sounds whose timbre matches
the actual material. File leading silence and internal peak matter: measure
and audition the sound's contact point, then align that point to the event.

## Music clock and permissions

Select music from material/emotional intent and the existing explicit taste
choice. Record creator, source, rights, use case, local hash and any credit or
redistribution conditions for every used file. Verify relevant current source
terms when sourcing media. A software MIT license and an upstream library's
CC0 label do not establish rights to arbitrary replacement tracks. The recipe
does not restrict legitimate user-licensed assets to a two-license whitelist.
Do not bundle, commit or distribute raw restricted audio as reusable skill media.

When beat mapping helps, inspect the actual placed track. Verify downbeats and
tempo changes against audible events/waveform across the head, middle and tail;
kick energy alone does not prove every genre's beat or a constant tempo. Report
uncertain/half-time/offbeat detection plainly. Recompute after trims, loops,
stretch or placement changes. Prefer adjusting flexible accents or music placement
inside approved constraints; changing an approved speech cut needs a new timing
decision/approval. Meaning and intelligibility take precedence over beat error.

## Mix, measure and listen

Use existing `audio-plan/v1`: source assessment, restoration decisions, scene
roles, masking/intelligibility, synchronization and project delivery targets.
Dialogue priority is normally appropriate for explanation, while a music-led
piece may have a different declared primary role. Fixed gain differences and
ducking depths are starting experiments, not guarantees. Audition speech with
effects/music on headphones and the target phone; inspect mono compatibility
and any channel-dependent loss.

Use verified existing audio mix tools; keep runtime media playback framework-owned.
Measure the final encoded artifact for integrated loudness, loudness range,
true peak, silence and decode integrity against the delivery spec. True peak
uses dBTP; do not confuse it with sample peak dBFS. There is no universal
-16 LUFS/-4 dB ceiling in this recipe. Changing the mix/re-encoding creates a
new artifact hash and invalidates affected final review evidence.

Review frames plus waveform around contact, longest effect, strongest reveal,
densest speech, head/tail and every music/effect seam. These diagnostics prove
placement, not that the sound is appropriate. Give the human the riskiest
timestamps as review aids while retaining the required complete encoded playback
and all Quality review points. Five spot checks cannot replace complete review.
Capture actual measured results, accepted rights/credits, cue changes and audio
QA in existing envelopes before the Quality/adapter publication gate.

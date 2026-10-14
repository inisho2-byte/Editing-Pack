# Audio analysis and choreography recipes

These recipes supply the mechanics for [SKILL.md](<SKILL.md>); they do not grant
render approval. Use the existing local HyperFrames core/CLI/animation skills
at authoring time and inspect its installed API/help. Discover a suitable
registry visual before building a named effect; reuse only compatible local
assets. No installation is implied by a missing registry item.

## Offline analysis

The owned helper is Editing-Pack
[`Editing_OS/Tools/editing-workbench/audio_motion.py`](<../../Tools/editing-workbench/audio_motion.py>).
It uses only Python's standard library. Run from the toolkit root:

```powershell
../editing-pack-env/Scripts/python.exe -B Editing_OS/Tools/editing-workbench/audio_motion.py --config config/toolkit.local.json 'path/to/job/analysis.wav' --out 'path/to/job/audio-motion.json' --fps 30000/1001 --bands 24
```

The source must be an uncompressed signed 16-bit PCM WAV, 8–192 kHz, 1–8
channels. Use a verified local FFmpeg executable to create a **disposable
analysis copy**, keeping channels and the actual placement duration:

```powershell
ffmpeg -n -i 'path/to/selected-track.wav' -vn -c:a pcm_s16le 'path/to/job/disposable/analysis.wav'
```

For MP3/AAC or edits, first establish the final placed start/duration and decoder
delay; analyze the conformed placed audio. Register the original and derived
WAV hashes and conversion command. The JSON hashes the analyzed WAV, not the
original compressed file; keep that mapping explicit. Never change the played
audio just to satisfy analysis. The JSON output path must be new; the helper
refuses to overwrite any existing output or input.

Output fields:

| Field | Meaning |
|---|---|
| `source_sha256` | Identity of the analyzed WAV bytes |
| `fps` | Reduced rational frame rate; use exactly this rate in the composition |
| `frame_count` | Ceiling of sample duration × FPS; last frame starts before audio ends |
| `frames[i].rms`, `.peak` | Raw linear amplitude over a centered FFT window, mean channel energy; not LUFS or whole-program peak QA |
| `frames[i].bands` | Fixed-floor, windowed FFT magnitudes mapped to 0–1 with offline attack/release smoothing |
| `band_edges_hz` | Log-frequency band edges; sparse low-frequency bands can share their nearest FFT bin |
| `fft_size`, `scale` | Reproducible analysis settings, including dB floor and smoothing times |

The 24-band, 1024-sample, 35ms attack/180ms release defaults are analysis starting
points; their aesthetic effect needs treatment selection. Silence produces
zero, with no decorative minimum bar. Independent channel-energy averaging
avoids false silence on opposite-phase stereo. FFT bands are uncalibrated
visualization data, not a spectral metering instrument. Use 2048/4096 samples
when low-frequency resolution matters; longer windows blur transient timing.
This helper supplies an **amplitude envelope**, not a signed waveform trace or
beat grid. Draw a true waveform from actual PCM samples or a verified existing
waveform specialist; never label equalizers or invented bars as measured waves.

Smoothing is computed once in source-frame order and baked into JSON. Rendering
simply reads the requested frame; it never mutates a previous-frame accumulator.
Expect CPU cost to grow with duration, FFT size and channel count. The helper
caps analysis at 72,000 frames and fails on invalid/truncated PCM. An accepted
PCM file still needs the separate audio QA required by Editing OS.

## Frame-derived motion in HyperFrames

Inline the reviewed JSON during build or stage it as a local build input; no
render-time remote fetch. Use the same rational FPS and source-time mapping as
the actual audio clip. An isolated visualizer begins at t=0. A trimmed/offset
clip maps `source_time = output_time - placement_start + source_in` before
indexing; silence/absent clips produce zeros. For loops, make the mapping and
audio seam explicit. A changing clock invalidates all downstream evidence.

For modest scenes, explicit GSAP frame sets provide simple random-access
reproducibility. On each sized bar child (not its timed clip wrapper), schedule:

```javascript
const fps = fpsNumerator / fpsDenominator; // from the reduced JSON rate
const tl = gsap.timeline({paused: true});
for (let i = 0; i < analysis.frames.length; i++) {
  const at = placementStart + i / fps;
  analysis.frames[i].bands.forEach((value, b) => {
    tl.set(barNodes[b], {scaleY: value, transformOrigin: '50% 100%'}, at);
  });
}
// Add finite scene/treatment motion before registering the completed timeline.
window.__timelines[compositionId] = tl;
```

This excerpt assumes the analyzed audio begins at source zero and is placed
without cuts/stretching. Apply the mapping above for other cases. Set every bar's
initial scale to zero through GSAP before `placementStart`, and schedule zero at
the actual audio end if the composition continues. Give bars real fixed width
and maximum height; their container must fit that height at the largest frame.
Do not put conflicting initial CSS transforms or CSS transitions on those nodes.
The root duration is the actual delivery duration, not a guessed song length.
Audio uses the runtime's timed `<audio id="..." src="...">` clip, never `.play()`.

This approach costs `frames × bands` timeline sets. Benchmark a representative
excerpt before a long song. If that cost is excessive, use a verified seekable
runtime adapter that computes pure state from its requested time; do not switch
to a timer or live audio playback to improve preview performance. DOM state
must match when seeking to the same time in forward and reverse order.

For energy-driven title/accent motion, derive the target from the recorded RMS
and approved bounded gain. Keep the title readable and avoid a new focal event
on every beat. Do not use dB-band values as a physical loudness claim. Any
easing/filtering must be baked or a pure time function. Large glows and rapidly
alternating brightness need specific visual safety review; calm/reduce motion
when the selected treatment or accessibility requirement calls for it.

## Lyrics and section progression

Use a corrected, forced-aligned lyric source with the same audio hash, language,
alignment model and correction identity as the played track. After editing,
consume approved `retimed_words`. Generate phrases through the existing
Captions engine under its adapter capability. A full-screen lyric stage is a
layout choice; it does not create a second word clock.

When reading LRC candidates, recognize metadata, offsets, repeated timestamps
and blank lyric/gap markers. Validate nonnegative ordered times, preserve
repeated verses, and verify ends against sung offsets/silence and actual track
duration. Do not derive the final end as `start + 5`; do not silently drop
malformed or duplicated lines. LRC line starts do not establish word-level
alignment. Review both first and last onsets and interior drift; one global
offset cannot fix tempo drift or text/audio mismatch.

Use musical sections as evidence for scene planning, not automatic scene swaps.
A verse can orient, a chorus can provide payoff, and a break can recover; map
them to the actual editorial-intent roles when useful. Stable layouts can hold
through a section. Change the treatment at a meaningful progression rather
than cycling hue across the whole track. Credits come from the actual rights
ledger; never insert vendor/generated-by branding by default.

## Review points

Record the first/last frame, silent/quiet/peak passages, each section transition,
longest lyric, every chosen caption activation, peak geometry and glyph edge
case in the existing review plan. Test target aspect ratio and 50%-linear-scale
readability. Compare forward/reverse seek state and independent render output.
Verify the actual encoded audio at head/middle/tail and after every cut/loop.
Every new compression/export invalidates the previous final artifact hash.
Platform upload limits are delivery inputs to verify at use, not copied static
limits from the vendor skill. A passing helper test does not establish encoded
playback, accessibility, lyric accuracy, graphics QA or publication readiness.

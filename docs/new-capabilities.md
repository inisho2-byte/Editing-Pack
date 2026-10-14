# Generated-input capability examples

Run from the toolkit root after [installation](installation.md) and external
[configuration](configuration.md). Keep each new job name unique. Every example
requires explicit draft consent and writes only to `workspace_root/jobs/<name>`.
No real footage, speech, approvals or downloaded reference media is used.

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
$Examples = 'Editing_OS/Tools/editing-workbench/capability_examples.py'
& $ToolkitPython -B $Examples --config config/toolkit.local.json audio --job-name pcm-demo --allow-unapproved-draft-treatment
& $ToolkitPython -B $Examples --config config/toolkit.local.json style --job-name palette-demo --allow-unapproved-draft-treatment
& $ToolkitPython -B $Examples --config config/toolkit.local.json studio --job-name object-demo --allow-unapproved-draft-treatment --render --capture software
```

The audio example generates two seconds of mono 16 kHz signed 16-bit PCM: one
second at 440 Hz, then one at 880 Hz. `evidence/audio-motion.json` has 60 frame
samples at 30000/1001 fps, source SHA, frequency bands, RMS/peak and bounded
attack/release envelopes. The dominant bands shift with frequency. For motion,
index this frozen array from absolute output time; never integrate mutable live
audio state. Analysis itself is not an encoded visualizer. Placement starts at
zero here; real edited audio must use its final placement and retimed timeline.

The optional style example generates a 160 by 100 opaque RGBA palette. It inspects
ROI `[20,20,120,60]` and subject `[20,20,50,60]`; the subject is cyan and the ROI
also contains amber and dark background. `evidence/style-observations.json`
records bounded image geometry, palette/alpha and source identity. Pixel
observations do not infer artistic intent or choose a treatment. `--render` is
refused for audio/style because these commands create analysis fixtures.

The studio example generates a three-second 1080 by 1920 draft with physical
folder/cards, hinge motion, lighting and shadows. It stages configured Three.js,
GSAP and Inter resources into the external job, with notices and hashes. It
checks readiness at three times, renders with one software worker, and decodes
the MP4 through the Quality engine. `ready` and `publication_approved` remain
false. Software rendering is expensive; allow several minutes for this short
full-size scene. Hardware capture is experimental: the fresh independent hardware
repeat differed and cannot satisfy a deterministic production gate.

Use `--example` to choose `folder-cards-rise`, `cards-scatter-file-in`,
`mat-loupe-stamp`, `monitor-timeline` or `tablet-over-footage`. The last example
uses a generated abstract background rather than real footage. Without `--render`
the command prepares source only. Missing resources fail before job creation;
existing jobs are never overwritten. Failed later rendering retains diagnostics
under `cache`, and must not be reported as a successful demo.

```powershell
& $ToolkitPython -B scripts/run_checks.py --config config/toolkit.local.json --style-analysis --graphics --3d-browser
```

The browser profile exercises forward/backward/random seeks, A-B-A and shuffled
repeat snapshots, resource failures, host offsets, shared resource disposal,
readiness and nonblank frames. Required enabled profiles refuse missing tools,
skips and zero tests. See [verification](verification.md) for current evidence.
The [synthetic clock](../examples/synthetic-clock/README.md) remains the timing
and gate-refusal tutorial. No fixture produces a human publication approval.

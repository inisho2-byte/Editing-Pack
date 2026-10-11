# A governed editing job

Start with [capabilities](capabilities.md). This guide explains production and gives command templates for genuine job files. It does not claim the complete clean rendering workflow is verified. Core onboarding is [getting started](getting-started.md); synthetic runnable walkthroughs are prepared separately.

## 1. Define the job and load its authority

Create a new job folder in the configured external workspace. Keep the brief, authorized sources, references and delivery spec there. Load the five documents in [START_HERE](../Editing_OS/Skills/START_HERE.md) before generation. Define the goal, audience, accessible media, rights, frame size/rate, output platform, evidence and review requirements in `production-context/v1`.

Hash the current governing document bytes into the context. An old context or fixture cannot establish authority for this job. Changes require updated context and revalidated dependent authority. Validate document content, then run adapter preflight with the actual required contracts/evidence.

From the toolkit root after installation:

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
$JobRoot = [IO.Path]::GetFullPath('../editing-workspace/jobs/my-job')
& $ToolkitPython -B 'Editing_OS/Video Editing/Contracts/validate.py' production-context "$JobRoot/contracts/production-context.json"
& $ToolkitPython -B 'Editing_OS/Video Editing/Engines/Orchestration_adapter/adapter.py' --config config/toolkit.local.json preflight --context "$JobRoot/contracts/production-context.json" --stage before-execution --contract "editorial-intent=$JobRoot/contracts/editorial-intent.json" --contract "taste-selection=$JobRoot/contracts/taste-selection.json" --output "$JobRoot/evidence/preflight.json"
```

These templates assume genuine files exist. Repeat `--contract KIND=PATH` and `--evidence PATH` for all context requirements. Preflight may correctly reject missing evidence; do not remove requirements or edit pass flags to bypass it. `--help` lists stages and commands.

### Refresh the five current document hashes

Draft the actual job context first using the schema/examples as shape references; replace illustrative sources, rights, goals and evidence requirements with actual job facts. After defining $JobRoot and $ToolkitPython above, this updates only the five governing references in that existing context. It does not approve source rights, timing, treatment or publication.

```powershell
$ContextPath = Join-Path $JobRoot 'contracts/production-context.json'
$Context = Get-Content -LiteralPath $ContextPath -Raw | ConvertFrom-Json
$EditingOsRoot = Join-Path (Get-Location).Path 'Editing_OS'
$GoverningPaths = @{
    master_prompt = 'Skills/MASTER_PROMPT.md'
    taste_profile = 'Skills/TASTE_PROFILE.md'
    tool_routing = 'Skills/TOOL_ROUTING.md'
    quality_standard = 'Skills/QUALITY_STANDARD.md'
    editing_handbook = 'Skills/Video editing handbook/Elite_AI_Video_Editing_Workflow.md'
}
foreach ($Document in $Context.governing_documents) {
    if (-not $GoverningPaths.ContainsKey($Document.role)) { throw 'Unknown governing role' }
    $Document.path = $GoverningPaths[$Document.role]
    $Document.sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $EditingOsRoot $Document.path)).Hash.ToLowerInvariant()
}
[IO.File]::WriteAllText($ContextPath, ($Context | ConvertTo-Json -Depth 100), [Text.UTF8Encoding]::new($false))
& $ToolkitPython -B 'Editing_OS/Video Editing/Contracts/validate.py' production-context $ContextPath
```

The adapter then verifies these bytes and all required job evidence. Never use this snippet to relabel old approvals or synthetic alignment as current authority.

## 2. Establish one editorial clock

Inspect footage and obtain genuine forced-aligned source words. [WhisperX setup](optional-tools.md#alignment-and-models) is separate. Raw Whisper or fabricated timestamps are diagnostic/example data, not production alignment evidence.

Plan intent/scenes, propose word-safe ranges, review the actual EDL and bind approval to its hashes. The adapter checks EDL approval and selected treatment before issuing render authority. Keep the resulting timeline map and retimed words as output-clock evidence for both captions and graphics. Do not invent a second clock by transcribing the edited output again.

## 3. Select treatment explicitly

Show useful caption, grade, music, layout and graphics options on actual material where unresolved. Record the selected `taste-selection/v1` option. Silence, platform labels, test defaults and AI preference do not select treatment. A customized taste profile informs proposals but does not replace a per-job selection.

## 4. Build through the adapter

Consume verified timing/treatment authority through the owned adapter and component render authorizations. Direct engine calls, vendor checkpoints and local render manifests cannot confer production authority. Keep inputs, derived artifacts, logs and rights/provenance with the external job.

The adapter includes `check-edl-approval`, `apply-approved-edl`, `authorize-caption-render` and `check-caption-timing`. See the [component guide](<../Editing_OS/Video Editing/Engines/Orchestration_adapter/README.md>) and `--help`. Do not mark arbitrary legacy JSON as passing evidence.

## 5. Decide the delivery form

| Result | Meaning | Still required |
|---|---|---|
| HTML/Studio preview | Working composition/timing/treatment review | Encoded inspection and review |
| Flat MP4 | Playable rendered artifact | Its own QA, rights and human review; it is not an editable native project |
| Editable native handoff | Clip-accurate interchange for a selected editor | Target identity, installed import support and independent readback/playback |
| Publication-ready artifact | Quality `ready: true` for exact encoded bytes and passing adapter check | Actual upload authorization and destination requirements |

Resolve is a guarded prototype, not full production assembly. FCPXML needs a matching installed DTD and xmllint. An interchange file or serialization pass does not prove native import.

## 6. Inspect and review the encoded export

Quality evaluates encoded media, spec, component evidence, required regression render or justified waiver, and human review. Generate a template, inspect the complete video and required scene/density/device checks, then record actual artifact-bound answers. A pending template is not a completed review.

```powershell
& $ToolkitPython -B 'Editing_OS/Video Editing/Engines/Quality_engine/qa.py' "$JobRoot/exports/final.mp4" --config config/toolkit.local.json --spec "$JobRoot/contracts/quality-spec.json" --print-review-template
```

This prints a template, not approval. Feed completed review and required evidence into adapter `run-quality`, then `assert-publishable` against the exact same export. Video readiness, permission to upload and toolkit release approval are separate decisions.

## When something changes

Changing cuts invalidates dependent timing/caption/graphics evidence. Changing treatment requires renewed selection and dependent render evidence. Changing export bytes requires matching fresh encoded QA and human review. Correct mismatches rather than carrying old approvals forward.

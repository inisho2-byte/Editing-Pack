# Getting started

This is the shortest verified core path: diagnose the setup and validate a synthetic contract. It does not require speech models, a native editor, a hosted image account or graphics packages. A rendered synthetic tutorial will be added in the examples step; a complete fresh production workflow is not yet certified.

## 1. Prepare the three locations

Keep the toolkit checkout, Python environment and job workspace separate. Complete [installation](installation.md). Commands run from the toolkit root in PowerShell. Choose your actual workspace; this sibling path is a generic example.

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
$JobWorkspace = [IO.Path]::GetFullPath('../editing-workspace')
```

Set config `workspace_root` to that same absolute path. Configure FFmpeg/FFprobe or put both on PATH. Keep `config/toolkit.local.json` local. The example config is not auto-loaded, and placeholders cannot stand in for executable files.

## 2. Diagnose your machine

```powershell
& $ToolkitPython -B 'Editing_OS/Tools/editing-workbench/workbench.py' --config config/toolkit.local.json doctor --out "$JobWorkspace/evidence/doctor.json"
```

Expected: exit 0 and a JSON output location. Open the report and check that `tools.ffmpeg.available` and `tools.ffprobe.available` are true. Doctor exit 0 means the report was written; it does not mean every optional tool is installed. Doctor never installs missing tools. See [troubleshooting](troubleshooting.md).

## 3. Validate a contract fixture

```powershell
& $ToolkitPython -B 'Editing_OS/Video Editing/Contracts/validate.py' production-context 'Editing_OS/Video Editing/Contracts/examples/production-context.v1.example.json'
```

Expected: exit 0 and `"valid": true`. This validates JSON shape and semantic rules. The adapter separately verifies live governing bytes and actual job evidence. Fixture source locators, timestamps and approvals are illustrative; no bundled source clip or real approval backs them.

## 4. Run the owned core checks

```powershell
& $ToolkitPython -B scripts/run_checks.py --config config/toolkit.local.json
```

Expected: each group reports `passed: true`, no skipped checks, exit 0. Core contains 184 checks; adding `--graphics` after optional graphics setup runs 213. Results/logs go in `workspace/cache/checks/`. Failures and skips are not successful verification. Test media is generated in external scratch, not taken from your projects.

## 5. Run the offline draft walkthrough

Follow the [synthetic clock tutorial](../examples/synthetic-clock/README.md). It generates test footage externally, creates an unapproved captioned draft, compares two encoded renders, and checks missing/stale authority refusals. No model, paid service or recorded voice is used. Expected tutorial success still has `ready: false`.

## 6. Choose what to learn next

Read [architecture](architecture.md), [capabilities](capabilities.md) and [workflow](workflow.md). Load [START_HERE](../Editing_OS/Skills/START_HERE.md) before directing an editing agent. Keep the real brief, media, contracts and evidence in a new external job folder. Do not copy synthetic approvals into it.

For captions from audio, inspect [alignment setup](optional-tools.md#alignment-and-models) before installing heavy dependencies. Graphics needs the explicit pinned resources. You can work with supplied genuine aligned words without invoking local transcription.

# Editing workbench

Diagnostics, media inspection, frame-grid drafts, approved handoff planning, guarded FCPXML and independent readback comparison. The workbench consumes adapter authority; it cannot grant publication readiness.

Start with [installation](../../../docs/installation.md), [configuration](../../../docs/configuration.md) and [capabilities](../../../docs/capabilities.md). Commands run from the toolkit root with external media/scratch/mailboxes/diagnostics.

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
& $ToolkitPython -B 'Editing_OS/Tools/editing-workbench/workbench.py' --help
& $ToolkitPython -B 'Editing_OS/Tools/editing-workbench/inventory.py' --help
& $ToolkitPython -B 'Editing_OS/Tools/editing-workbench/hyperframes_launcher.py' --help
```

| Command | Purpose and boundary |
|---|---|
| doctor | Writes diagnostics without installs; inspect tool availability, not just exit status |
| inspect | Probes selected media |
| snap-edl | Writes a new frame-grid draft requiring renewed approval |
| plan | Consumes adapter-approved timing and writes a handoff plan |
| fcpxml | Requires installed matching DTD and xmllint; import remains unverified |
| compare | Checks independently extracted native timeline structure, not playback |

Use COMMAND --help for required files. Synthetic test approvals/timestamps cannot authorize a real handoff. The original reviewed EDL is preserved when creating a snapped draft.

## Native prototype and previews

Resolve Lua/MCP offers bounded reads and an authorized verified-empty-project connection test. Supply identity/mailbox in Python and native process. Full native assembly/grade/mix/export is not implemented here. Premiere/Final Cut are conditional; CapCut native interchange is absent. MP4 is not an editable project.

The launcher retains GUI/CLI modes with owned previews. Closing it stops its process tree; occupied port 3100 is refused. Windows child consoles are suppressed, logs stay external and no sign-in service or automatic install is created.

Code is MIT; this guide is CC BY 4.0 with MIT snippets. See [workflow](../../../docs/workflow.md) and [optional tools](../../../docs/optional-tools.md).

## New diagnostic/draft capabilities

audio_motion.py analyzes conformed PCM with rational FPS and source hashes. style_inspect.py requires the optional pinned Pillow profile and supplies bounded ROI/alpha/palette observations. capability_examples.py generates external synthetic PCM/image/studio jobs only with an explicit draft flag; test_studio3d.py is an isolated required browser profile. None grants production approval. New external3D fields three_module and puppeteer_entry are optional; old configs remain valid.

# Video editing engine

Editorial planning and reviewed EDL execution, retimed words, captions/graphics handoffs and encoded review evidence. Legacy grade/caption/title APIs remain for compatibility and drafts; production authority comes from the owned adapter.

## Setup and use

Start with [installation](../../../../docs/installation.md), [configuration](../../../../docs/configuration.md) and [workflow](../../../../docs/workflow.md). Run commands from the toolkit root using the isolated core interpreter. Keep job outputs in the selected external workspace.

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
& $ToolkitPython -B 'Editing_OS/Video Editing/Engines/Video editing engine/engine.py' --help
```

See [capabilities](../../../../docs/capabilities.md) for tested limits. All example source locators, timestamps and approvals are synthetic; no example authorizes a real job. Documentation is CC BY 4.0; code/snippets and JSON operational material are MIT under [license scope](../../../../LICENSE-SCOPE.md).

# Hosted image utility

Validates structured prompts and plans optional hosted image requests. Live paid execution is unverified here and requires environment key, execute flag, sufficient cost approval and acknowledged API terms. Verify current provider prices/rights first.

## Setup and use

Start with [installation](../../../../docs/installation.md), [configuration](../../../../docs/configuration.md) and [workflow](../../../../docs/workflow.md). Run commands from the toolkit root using the isolated core interpreter. Keep job outputs in the selected external workspace.

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
& $ToolkitPython -B 'Editing_OS/Photo editing/Engines/Ideogram4_engine/ideogram4_hosted.py' --help
```

See [capabilities](../../../../docs/capabilities.md) for tested limits. All example source locators, timestamps and approvals are synthetic; no example authorizes a real job. Documentation is CC BY 4.0; code/snippets and JSON operational material are MIT under [license scope](../../../../LICENSE-SCOPE.md).

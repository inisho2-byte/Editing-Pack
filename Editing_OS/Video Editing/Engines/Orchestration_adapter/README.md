# Orchestration adapter

The owned authority boundary checks current governing hashes, contracts, evidence, approved EDL/treatment and post-cut timing. It issues bounded render authorizations and asserts readiness for one exact artifact. CLI commands include preflight, check-edl-approval, apply-approved-edl, authorize-caption-render, check-caption-timing, run-quality and assert-publishable.

## Setup and use

Start with [installation](../../../../docs/installation.md), [configuration](../../../../docs/configuration.md) and [workflow](../../../../docs/workflow.md). Run commands from the toolkit root using the isolated core interpreter. Keep job outputs in the selected external workspace.

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
& $ToolkitPython -B 'Editing_OS/Video Editing/Engines/Orchestration_adapter/adapter.py' --help
```

See [capabilities](../../../../docs/capabilities.md) for tested limits. All example source locators, timestamps and approvals are synthetic; no example authorizes a real job. Documentation is CC BY 4.0; code/snippets and JSON operational material are MIT under [license scope](../../../../LICENSE-SCOPE.md).

# Editing-Pack

A source toolkit for AI-assisted video editing: an editing handbook, operating instructions, validated production contracts, Python engines and finishing tools. It is for editors and developers who want an inspectable workflow with explicit human decisions.

**Status:** v0.1.0-rc.1 is published; this source proposes v0.2.0-rc.1. The expanded candidate has 209 core checks and separate style, graphics and native 3D browser profiles. Final fresh-candidate verification and publication review are required before the proposed release. See the [verification scope](docs/verification.md) and [capability matrix](docs/capabilities.md). Real productions need job-specific evidence.

## Start here

1. Follow [installation](docs/installation.md) using a separate Python environment and external workspace.
2. Complete [getting started](docs/getting-started.md): diagnostics and synthetic contract validation, with no paid API or model download.
3. Run the [offline synthetic walkthrough](examples/synthetic-clock/README.md) to inspect timing, draft captions, encoded QA and gate refusals.
4. Read [architecture](docs/architecture.md), then the [production workflow](docs/workflow.md) before using your own footage.
5. Choose a specialist in the [skill index](Editing_OS/Skills/README.md) and try the [generated-input examples](docs/new-capabilities.md).

After installation and local configuration, run these from the toolkit root:

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
& $ToolkitPython -B scripts/run_checks.py --config config/toolkit.local.json
& $ToolkitPython -B 'Editing_OS/Video Editing/Contracts/validate.py' production-context 'Editing_OS/Video Editing/Contracts/examples/production-context.v1.example.json'
```

The first command runs core checks using synthetic media in your external workspace. The second verifies the example's schema and semantic constraints; it does not authorize editing. See [getting started](docs/getting-started.md) for expected results.

## What is included

| Layer | Purpose |
|---|---|
| [Handbook](<Editing_OS/Skills/Video editing handbook/Elite_AI_Video_Editing_Workflow.md>) | Editorial craft and reasoning; empirical claims have scope limits |
| [Operating instructions](Editing_OS/Skills/START_HERE.md) | Task entry, taste, routing, scene planning and quality requirements |
| [Contracts](<Editing_OS/Video Editing/Contracts/README.md>) | Context, intent, taste selection, approvals and evidence formats |
| [Owned engines](<Editing_OS/Video Editing/Engines/README.md>) | Editorial timing, captions, graphics, orchestration and encoded QA |
| [Workbench](Editing_OS/Tools/editing-workbench/GUIDE.md) | Diagnostics, frame-grid drafts and conditional editable handoffs |
| [Hosted image utility](<Editing_OS/Photo editing/Engines/Ideogram4_engine/README.md>) | Structured image requests with explicit paid execution controls |

The source checkout contains no user footage, job transcripts, real approvals, models, fonts, installed environments or third-party specialist clones. Keep jobs outside it. A `.gitignore` is an additional convenience, not a privacy boundary.

## Decisions stay with the editor

A real production job needs genuine forced alignment, a reviewed and hash-bound EDL, post-cut retimed words, explicit treatment selection, encoded-artifact evidence and exact-hash human review. A preview or passing test cannot supply those decisions. [Workflow and review](docs/workflow.md) explains the sequence and the distinction between a review MP4, an editable handoff and publication readiness.

## Documentation

- [Installation](docs/installation.md) and [configuration](docs/configuration.md)
- [Getting started](docs/getting-started.md) and [troubleshooting](docs/troubleshooting.md)
- [Architecture](docs/architecture.md), [capabilities](docs/capabilities.md) and [optional tools](docs/optional-tools.md)
- [Privacy and job workspaces](docs/privacy.md)
- [Contributing](CONTRIBUTING.md), [maintenance](docs/maintenance.md), [changelog](CHANGELOG.md) and [security reporting](SECURITY.md)

Owned code, tests, schemas and operational instructions are **MIT**. The handbook and explanatory documentation are **CC BY 4.0**, with MIT code snippets. See [license scope](LICENSE-SCOPE.md), [MIT](LICENSE), [CC BY 4.0](LICENSE-DOCS) and [third-party notices](THIRD_PARTY_NOTICES.md). External tools, models and services retain their own terms.

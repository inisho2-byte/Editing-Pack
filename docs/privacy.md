# Privacy and job workspaces

Keep reusable source separate from the projects made with it. Use a dedicated external workspace for private media, transcripts, briefs, references, contracts, selections, reviews, renders, mailboxes and diagnostics. [Configuration](configuration.md) refuses overlapping roots and outputs inside the toolkit, including resolved junctions.

| Material | Home |
|---|---|
| Reusable owned code, generic instructions, sanitized tests | Toolkit source after review |
| Media, voices, screenshots, transcripts and client/personal context | External job `inputs/` and `brief/` |
| Real context, approvals, treatment choices and reviews | External job `contracts/` and `evidence/` |
| Preview projects and exports | External job `work/` and `exports/` |
| Environments and model weights | External dependency/cache locations |
| Local paths/config | Ignored local or explicit external config |
| Provider keys | Process environment or user-managed secret store |

An ignored file can still be force-added, copied into a PR or archived. Review exact files and Git diff before publishing. Logs, metadata, screenshots, inline examples and old history can disclose private content too.

## Personal taste and tracked instructions

Keep the shared taste template generic. Put personal references, project preferences and selection history in the external job brief/contracts. If you customize a tracked governing document locally, review that source change before any public push and refresh the job context hashes. Ignore rules do not protect already tracked files.

## Sharing a bug or example

Use synthetic text and generated test media. Remove usernames, absolute paths, customer names, private URLs, transcripts, thumbnails, account identifiers and tokens. Share a minimal sanitized error excerpt, not a workspace, local config, environment dump or real approval record.

Suspected security/privacy exposure uses [private reporting](../SECURITY.md). Do not put an exploit, credential or exposed project in a public issue. Credential revocation and controlling copies are separate from deleting a file in a later commit.

## Services and network access

Local core checks require installed dependencies but do not call a paid provider or download speech models. Optional installs, model loads, hosted requests and specialists may use network services. Inspect data handling/rights before sending job material. Toolkit licenses do not license your media or override service terms.

## Public release review

A source release needs exact file review, provenance/licenses, maintained secret scanning and privacy review of content/history/assets. Scanners do not detect every private name or project example. Label synthetic examples/approvals clearly. Detailed scan logs and excluded-project inventories stay private.

Release exports reject job/workspace folders, installed dependency folders, local `.local.json` settings, unknown files, escaping links and binary/archive payloads, even when someone mistakenly lists protected files in a manifest. Exact file review and content scanning remain required before publication. The exporter defaults to a dry-run and keeps its manifest and detailed report outside the checkout.

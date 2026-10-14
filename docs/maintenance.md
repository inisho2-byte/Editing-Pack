# Maintenance and releases

Preserve reusable source/private job separation. Read [contributing](../CONTRIBUTING.md), [privacy](privacy.md) and [security reporting](../SECURITY.md). Detailed inventories, scan logs and real job evidence remain external.

## Routine changes

- Scope changes to owned source; install specialists externally and retain upstream terms.
- Recheck versions/platform requirements when intentionally updating dependencies. Record pins, tested locks, package/resource integrity and verification limits in the manifest; never silently switch to latest.
- Run affected checks. Core/config/authority changes need cross-component checks; graphics requires pinned media/lint checks. Failures/skips are incomplete verification.
- Keep links, commands and capability claims consistent with code; test new platforms before advertising support.
- Refresh fixture hashes when governing documents change. Revalidate actual job authority independently.

## Version practice

Maintain [CHANGELOG](../CHANGELOG.md)'s Unreleased section. The published baseline is v0.1.0-rc.1; this update proposes v0.2.0-rc.1, subject to exact-candidate release review. Use patch versions for compatible fixes, minor versions for compatible capabilities and major versions for incompatible public CLI/config/schema behavior. Production schema versions are separate contracts; do not change v1 incompatibly in place.

Update `toolkit.json` release_version and candidate status only to describe the actual approved release. Tests are not publication permission. Release notes identify tested platforms, validation, migration and limits.

## Before publishing

1. Freeze/review the exact files/hashes, licenses/notices, generic examples and diff.
2. Run maintained secret scanning plus content/history/metadata privacy review. Keep sensitive findings private; review archives/assets separately.
3. Verify a clean checkout with documented setup, external workspace and synthetic walkthrough. Recheck missing-tool failures and authority refusals.
4. Review the exact candidate/version/notes with the owner before any public branch, PR, tag, archive or release.
5. Publish only approved source/assets and verify a fresh public clone afterward.

Tags, releases and generated archives are disclosure surfaces. Ignore rules and scanner passes do not authorize uploading a working directory. The controlled exporter requires a current exact manifest; its report is evidence, not publication permission.

## Background work and security

Previews stop with their owning launcher session. Do not register sign-in servers or detached workers without a separate explicit need. Keep external diagnostics readable, suppress Windows child consoles and respect other tasks' processes.

Keep private vulnerability reporting enabled and triage privately. Do not turn private reports into public issues automatically or promise an unestablished response SLA.

# Contributing

Contribute reusable improvements with synthetic examples and a clear reason. Keep personal/client projects, transcripts, account data and environments outside the repository. Read [privacy](docs/privacy.md), [architecture](docs/architecture.md) and [capabilities](docs/capabilities.md).

## Before opening a pull request

1. Reproduce on generic material and identify the affected component.
2. Follow [installation](docs/installation.md) with an external environment/workspace. Run affected checks; cross-component changes need the core runner, graphics changes need `--graphics`. Missing tools/skips are incomplete verification.
3. Preserve alignment, reviewed EDL/retiming, selected treatment, encoded QA and exact-hash human review. Add meaningful refusal regressions when changing these boundaries. Do not weaken approval checks to pass an example.
4. Update docs. If a governing document changes, refresh synthetic context hashes and re-run contract/adapter checks. Real jobs need independently renewed authority.
5. Review exact diff, sizes, ignored/untracked files, links, licenses and provenance. Exclude media, vendor clones, models, fonts and private scan reports.

Use the [PR template](.github/PULL_REQUEST_TEMPLATE.md) to describe resulting behavior, validation and limits. Public branches/PRs expose content immediately: inspect before pushing. Vulnerabilities use [SECURITY](SECURITY.md), not public issues or PRs.

## Ownership and licenses

Contribute material you own or are authorized to submit. Existing scope applies: code/tests/schemas/operational instructions MIT; explanatory docs/handbook CC BY 4.0 with MIT snippets. Identify new dependencies, assets and borrowing, and retain third-party terms/notices. See [license scope](LICENSE-SCOPE.md) and [notices](THIRD_PARTY_NOTICES.md).

## Releases

Update [CHANGELOG](CHANGELOG.md) under Unreleased. Follow [maintenance](docs/maintenance.md) for dependencies, evidence and publication review. A source release never certifies a user's video.

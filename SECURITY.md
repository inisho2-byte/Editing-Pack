# Security and private reporting

Use [GitHub private vulnerability reporting](https://github.com/inisho2-byte/Editing-Pack/security/advisories/new) for suspected vulnerabilities or accidental private-data exposure. Sign in and select **Report a vulnerability**. Reports go to maintainers privately; do not open a public issue with sensitive details. GitHub's [reporting guide](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately) explains the process.

Include affected revision/component, impact, a minimal synthetic reproduction and mitigation if available. Describe leaked keys by type/location; never attach live values, private footage, transcripts, full workspaces or personal configuration. Additional sensitive evidence needs an agreed private channel.

If the form is unavailable, request a private contact in an issue containing only “Please provide a private security reporting contact.” Do not describe the vulnerability there. No response-time guarantee, bounty or audit certification is promised.

## Supported scope

This is a prerelease candidate with no released supported-version matrix yet. Report against the current candidate or latest published release when one exists. External tools, applications, models and services have their own security/support processes. Coordinate dependency issues upstream without disclosing sensitive job data.

## Maintainer handling

Triage privately, establish affected revisions and contain exposure. Credentials may need revocation after source removal. Review fixes and sanitized regressions before coordinated disclosure. Deletion does not erase old Git objects, caches or downloaded copies. Publishing an advisory, scan log or affected user data requires an explicit disclosure decision.

# Security Policy

PrivateLabBench processes local scientific evaluation data, so security/privacy bugs can matter even when the project does not run a hosted service.

## Supported versions

Until stable release channels are established, security fixes target the current `main` branch and the most recent tagged release when one exists.

## Report a vulnerability privately

**Do not open a public GitHub issue for an unpatched vulnerability that could expose private data, credentials, artifact-signing secrets, local files, or code execution.**

Preferred reporting path after GitHub private vulnerability reporting is enabled for the public repository:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Include the affected version/commit, impact, reproduction steps, and any proposed mitigation.

Until that repository feature is enabled, contact the repository owner privately through the GitHub account/profile with a minimal initial description and arrange a private channel before sharing exploit details.

Do not send real private datasets, credentials, or secrets as part of a report. Use synthetic reproduction data whenever possible.

## What to include

A useful report contains:

- affected commit/version;
- affected command/module/artifact type;
- expected versus observed behavior;
- security/privacy impact;
- minimal reproduction using synthetic data;
- whether the issue is remotely triggerable or requires local file access;
- proposed fix or mitigation, if known.

## Security-sensitive areas

Examples include:

- path traversal or unintended local-file disclosure;
- reports/receipts leaking row-level private data;
- incorrect sanitization/sharing boundaries;
- signature/hash verification bypasses;
- unsafe deserialization or command execution;
- dependency or archive handling vulnerabilities;
- benchmark/plugin loading that executes untrusted code unexpectedly;
- privacy claims that materially misrepresent what an artifact protects.

A weak metric or research limitation is usually not a security vulnerability unless it creates a concrete confidentiality/integrity impact or a dangerously false security claim.

## Coordinated disclosure

Maintainers will try to acknowledge actionable reports, assess severity, develop a fix, and coordinate disclosure before exploit details are made public. Exact timelines depend on severity and maintainer availability.

If a vulnerability affects a released package, the fix should include an advisory/release note and a patched release when release infrastructure is available.

## Threat-model boundary

PrivateLabBench's local-first design reduces network exposure, but local software can still leak data through artifacts, paths, logs, dependencies, plugins, or unsafe file handling. Treat third-party task plugins and external prediction/data files according to their own trust boundaries.

See [`docs/privacy.md`](docs/privacy.md) for the difference between security, privacy attacks, heuristic perturbation, and formal privacy mechanisms.

# Public Release Audit

PrivateLabBench should not change from private to public until this audit passes on the full repository history.

## Automated checks

`.github/workflows/public-release-audit.yml` runs three independent jobs.

### Repository policy audit

`scripts/public_release_audit.py` checks:

- current-tree commercial/service paths remain absent;
- every tracked `examples/**/*.csv` fixture is declared synthetic and CC0-1.0;
- bundled benchmark packs declare synthetic provenance, no external derivation, and CC0-1.0;
- every direct runtime dependency in `pyproject.toml` has an explicit license-compatibility review entry;
- full Git history is available and inventoried;
- author/committer emails in history use GitHub noreply forms rather than exposing other addresses;
- historical paths matching `.env`, customer/pilot/dashboard/production/Postgres/sync/evidence patterns are inventoried for review.

Potential non-noreply emails are represented only by short SHA256 fingerprints in CI output; raw email addresses are not printed by the audit script.

### Gitleaks

Gitleaks runs after `actions/checkout` with `fetch-depth: 0`, so deleted/changed historical content is scanned rather than only the current tree.

### TruffleHog

TruffleHog provides a second history-oriented secret detector and reports verified/unknown findings. It is defense in depth; Gitleaks remains the full-history pattern scan including the root commit.

## Example/data review

[`../examples/PROVENANCE.md`](../examples/PROVENANCE.md) documents the repository example fixtures. The machine-readable audit manifest lists every tracked CSV so new undeclared example data fails CI.

Bundled benchmark packs maintain their own license/provenance declarations and are validated independently.

## Direct dependency license review

The direct runtime dependencies are reviewed in `audit/public_release_manifest.yaml` against their upstream license files:

- NumPy — BSD-3-Clause;
- pandas — BSD-3-Clause;
- scikit-learn — BSD-3-Clause;
- PyYAML — MIT.

These permissive licenses are compatible with the project's MIT distribution. Transitive dependency/license changes should still be reviewed when the dependency graph changes materially.

## Historical commercial files

The repository previously contained intentionally commercial/product-oriented code and documentation. The current public source surface removes those files, but their names may still exist in Git history.

Historical product filenames are not themselves a secret and do not require a history rewrite. A rewrite is warranted only if history contains actual credentials, private/restricted data, private personal information that should not be exposed, or other material that cannot safely become public.

## If a scanner finds a secret

Do not paste the finding into a public issue or PR comment.

1. Treat any credential that may have been committed as compromised and rotate/revoke it first.
2. Determine which commits/refs contain the material.
3. Rewrite affected Git history if public exposure would be unsafe.
4. Force-update all affected refs only after coordinating the rewrite.
5. Re-run both scanners against the rewritten full history.
6. Confirm downstream clones/forks/caches are handled as appropriate for the secret type.

Removing a secret only from the latest commit is not sufficient.

## Release decision

A passing audit establishes that the automated repository checks found no blocking condition. It does **not** itself change repository visibility, publish PyPI artifacts, enable GitHub Pages, or configure GitHub security/community settings.

Before public launch also confirm the outstanding live repository/release settings tracked in issues #8 and #10.

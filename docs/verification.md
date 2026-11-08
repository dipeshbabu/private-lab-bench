# Verification and its limits

The normal CI runs the complete base pytest suite on twenty-six configured OS/Python
combinations, with dedicated Linux jobs for optional scientific tools, OpenDP,
and actual gVisor execution. Lower dependency and Windows/macOS optional-backend
jobs expand this to forty-six JSON coverage reports, combined by
union of executed statements and branches, rather than averaging percentages.
Coverage must reach 85% statements and 75% branches, with every source file and
job report present. Unit tests and regression scenarios remain necessary even
when these floors pass: line coverage alone cannot prove concurrency behavior.

The independent plugin fixture is built as a wheel and installed into each clean
wheel/source environment. The CLI must discover it through installed Python
entry-point metadata, execute it, and produce a verifiable local receipt.

## Real public scientific inputs

[Real scientific parity](https://github.com/dipeshbabu/private-lab-bench/actions/workflows/scientific-parity.yml)
runs weekly at Monday 07:23 UTC, on changes to its workflow/parity/integration
definitions on main or Codex branches, and by manual dispatch. It checks all
six supported TDC tasks over five training seeds, all five supported Matbench
tasks/folds with two controls, and ten ProteinGym assays including the actual
upstream summary pipeline. Public inputs are checksum-pinned. Only aggregate
`verification.json` records are uploaded; no rows, predictions, model parameters,
or signing keys enter the result artifacts.

These jobs complement the fast synthetic contracts and real upstream scorers in
ordinary CI. They still cover a selected task/assay subset, not every upstream
leaderboard or scientific model. A scheduled-job failure requires investigation;
it must not be relabeled as successful validation.

## The actual released package

The onboarding job installs the current stable PyPI wheel with a fresh lookup,
rather than pinning an older release. The same first-session flow also runs daily
at 08:17 UTC and on manual dispatch in
[Released package onboarding](https://github.com/dipeshbabu/private-lab-bench/actions/workflows/released-package.yml).
It runs outside the checkout and verifies both local-only and explicitly approved
synthetic outputs. The release workflow additionally blocks unchecked SHAs and
tests both built distributions before publishing; see [releases](releases.md).

## Evidence that still needs people or additional implementation

Independent researcher sessions remain [pending](case_study/findings.md), at 0/3.
Automated checks are not independent usability or security/privacy audits.
PyPy and unlisted OS/version combinations
remain outside the [verified support matrix](support.md). Durable multi-process
privacy accounting and GPU/multi-file model sandbox execution remain documented
implementation boundaries, not capabilities claimed by these test results.

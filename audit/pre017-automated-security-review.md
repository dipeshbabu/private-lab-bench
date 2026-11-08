# Automated review before v0.1.7

The automated source review found no new reportable security findings in the
unreleased verification and extension changes. This is a static code review;
the independent human privacy/sandbox audit remains unavailable.

- Scan: `62e1aa1e-6cae-40bf-afc5-e879497ee549` (Codex Security 0.1.32).
- Reviewed range: `a6887994aec7b6c8b33955ddb9fb4004991f6adc` to
  `a0a0c9ba47283660a3c29f878950b550e7887409`.
- Coverage: all 54 changed files, including 26 source inventory files and 28
  documentation, test, example and constraint files; no source exclusions.
- Method: a fresh architecture review, separate privacy and sandbox source
  reviewers, and parent review of CI, release gates, scientific profiles and
  supporting files. Reviewers did not execute application code or tests.
- Outcome: zero new security candidates or unresolved source-review items.
  The two findings from the earlier full review of 122 package files were fixed
  in [PR #105](https://github.com/dipeshbabu/private-lab-bench/pull/105).
- Findings SHA-256: `2951f799cfab284a2005490749f3eae46a2b22e65b07d3fbf9f4db588592911a`.
- Coverage SHA-256: `1a10ece24d70c53a7bd9590a16f36bc21dceeb16992f3e09032635fc407b5165`.
- Reviewed package Git tree: `b32efc6507a70435acd3ec2d8e1acbf0546457a1`.

The follow-up corrects the sandbox command example and obsolete verification
limitations, and exercises the package through the actual module CLI. The
production package tree is unchanged. Final CI must pass before squash merge.

Separate engineering checks include 1,062 passing local tests, both clean
distribution installs, [83 real gVisor tests](https://github.com/dipeshbabu/private-lab-bench/actions/runs/42443464457/job/128617379708),
actual OpenDP releases, and [pinned upstream parity](https://github.com/dipeshbabu/private-lab-bench/actions/runs/42443464510)
for 40 TDC runs, 70 Matbench folds and 12 ProteinGym assays with two controls.
These checks do not establish physical storage durability, independent review,
GPU support, or protection against an operator restoring/cloning a privacy ledger.

The workbench reported rollout usage across five threads: 11,358,844 input
tokens (11,043,584 cached), 66,644 output tokens and 11,425,488 total tokens.
This is measured rollout accounting, including reused context.

v0.1.7 remains [on hold](../docs/release_readiness.md). No release is authorized
by this summary alone; code or runtime changes require review of their affected
boundaries.

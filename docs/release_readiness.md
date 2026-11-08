# v0.1.7 readiness

v0.1.7 is on hold. The published v0.1.6 files and tags remain unchanged.
The release workflow checks `audit/release-readiness.json` before building or
uploading a new release, in addition to requiring green CI for the exact commit.
An incomplete prerequisite blocks v0.1.7 and later versions, so choosing another
tag cannot skip the hold. Historical release reruns keep their existing behavior.

| Prerequisite | Required evidence |
| --- | --- |
| Failure-path tests | Regression tests for design audits, export policy/state, trends, and paired comparisons; retained coverage results |
| Dependency/platform coverage | Verified lower dependency line, declared platform/runtime jobs, and optional-extra checks |
| Automated security review | Source-backed report with findings fixed or explicitly accounted for; no claim of external independence |
| Independent privacy/sandbox audit | Review by someone separate from the implementation, with scope, revision, findings, and resolution evidence |
| Durable privacy accounting | Cross-process/restart budget enforcement, concurrency/crash tests, and documented operator assumptions |
| Multi-file CPU sandbox | Digest-bound model package, restricted mounts, resource limits, and actual gVisor runtime tests |
| Expanded benchmark parity | Additional versioned profiles with actual pinned upstream-data/scorer comparisons |
| GPU runtime validation | Tests on an appropriate Linux NVIDIA/gVisor host; mocked Docker arguments do not establish GPU support |

The maintainer currently has neither an independent reviewer nor a suitable GPU
host. Those requirements remain unavailable; automated tests and agent reviews
must not be recorded as substitutes. Complete the verifiable work and retain
the release hold. A later scope change requires an explicit maintainer decision
and an honest update to the documented capabilities and release requirements.

Each completed entry must link to its actual evidence. This record makes the
decision reviewable; it does not authenticate a reviewer or prove the contents
of a third-party report. Code and runtime changes made after a review still
require review of the affected boundaries.

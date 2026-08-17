# Governance

PrivateLabBench is currently maintainer-led and accepts community contributions through issues and pull requests. The governance model is intentionally lightweight while the public APIs and contributor base are still small.

## Maintainer

The current project maintainer is **Dipesh Tharu Mahato (`@dipeshbabu`)**.

Maintainers are responsible for:

- reviewing and merging changes;
- keeping releases, schemas, and documentation coherent;
- protecting local-first/private-data guarantees;
- enforcing the Code of Conduct and security process;
- triaging regressions and compatibility issues;
- deciding whether a contribution belongs in core, a plugin, or a benchmark pack;
- avoiding misleading scientific/privacy claims.

## Decision principles

For ordinary changes, decisions are made through issue/PR discussion and maintainer review.

When reasonable approaches disagree, prefer the option that best preserves:

1. correctness and reproducibility;
2. precise scientific/privacy semantics;
3. local-first operation;
4. backward compatibility of versioned protocols;
5. a small core dependency footprint;
6. extensibility through plugins/packs rather than special cases;
7. maintainability for outside contributors.

Popularity or implementation size alone is not sufficient reason to put something in core.

## Public API and protocol changes

The following require extra care:

- `prediction-table/*` schemas;
- `evaluation-receipt/*` schemas;
- `benchmark-pack/*` schemas;
- task/plugin entry-point behavior;
- report/manifest integrity semantics;
- privacy guarantee labels or release-policy meaning.

Backward-incompatible changes should use a new schema/version or provide an explicit migration/compatibility path with tests.

## Core versus plugin versus pack

### Core

Cross-domain functionality with broad use and lightweight dependencies.

### External plugin

Specialist tasks/models/dependencies that can evolve independently from core.

### Benchmark pack

A versioned evaluation protocol plus small/synthetic or license-compatible prediction examples.

Maintainers may ask a PR to move between these layers before accepting it.

## Review expectations

A pull request may be merged when:

- its scope is clear;
- tests and CI pass;
- relevant documentation is updated;
- privacy/data-sharing implications are addressed;
- artifact compatibility is understood;
- there are no unresolved security/license concerns.

Passing tests does not guarantee merge if the change expands scope in a way that conflicts with the project direction.

## Becoming a maintainer

As the community grows, contributors may be invited as maintainers based on sustained work such as:

- several high-quality merged contributions;
- reliable code review/issue triage;
- demonstrated understanding of architecture/privacy constraints;
- constructive community participation;
- willingness to maintain code after initial contribution.

Maintainer access should be granted gradually and can be scoped to areas of expertise before broader repository permissions.

## Conflicts of interest

Contributors and maintainers should disclose material conflicts when proposing or reviewing work that evaluates their own model/product/dataset or creates a benchmark where they have a direct competitive interest.

A conflict does not automatically disqualify participation, but relevant claims should be reviewable and reproducible by others.

## Changes to governance

Governance changes should be proposed in a dedicated issue/PR and should explain why the existing process is no longer adequate. As the maintainer group grows, this document can evolve toward explicit voting or multi-maintainer decision rules.

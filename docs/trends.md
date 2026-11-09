---
icon: material/chart-timeline-variant
---

# Longitudinal evaluation from receipts

Use `plb trend` to compare a fixed model's results over time without collecting prior raw datasets. Inputs are verified, already-shareable `evaluation-receipt/v1` artifacts. The result is a versioned `longitudinal-series/v1` artifact with source receipt digests, per-period scores, available uncertainty, practical changes, slice trajectories, and quality decisions.

```sh
plb trend jan.shareable.json apr.shareable.json aug.shareable.json --time 2026-01-01 --time 2026-04-01 --time 2026-08-01 --series local-assay-study@v1 --model published-model@weights-v2 --metric rmse --practical-threshold 0.02 --critical-slice site=lab-a --out reports/assay-trend.json
```

## Identity and time

Declare one collection date or timezone-aware timestamp for every receipt, in chronological order. Dates mean midnight UTC; timestamps are normalized to UTC. Duplicate times or receipts fail. Source publication/file dates are not inferred as collection dates: the release boundary deliberately removes those local metadata fields.

Model ID/revision, series ID/revision, and collection times are declarations. Available signer model statements and external-validation model identities must agree; immutable model artifact digests cannot conflict. Pin trusted issuers with `--trust-store` and `--require-trusted-signer` when identity matters. A self-contained hash alone does not prove honest execution or that runs belong to the claimed study.

Every source must have a successful release decision and compatible protocol digest, task, benchmark identity, input schema, and metric basis. Changing the model or scientific protocol starts a separately identified series. `--metric` defaults to the protocol primary metric; unsupported metrics fail. The default reference is the first period; `--reference-index` selects another zero-based reference explicitly.

## Changes and uncertainty

Each period records the selected score and available interval, raw and direction-adjusted changes from the reference and previous period, and relative degradation. Positive degradation always means worse performance. Relative change is unavailable when the reference is zero. Undefined scores and missing/incompatible intervals stay explicit.

A point change above `--practical-threshold` is marked `degradation`. Its separate `uncertainty_assessment` reports whether available marginal interval bounds are compatible with no material change. A small worsening point estimate is not automatically evidence of drift.

Receipts do not contain the joint bootstrap samples needed for a new paired or independent-cohort interval. The trend artifact instead reports the conservative difference of available marginal bounds. Two nominal 95% marginal intervals imply a union-bound coverage floor of 90% for that difference **conditional on their marginal coverage**; this does not require independent periods, and it is not a 95% paired interval. Bootstrap marginal coverage is approximate. Source-versus-itself comparisons are exactly zero. Perturbed metrics do not inherit clean-metric intervals.

Period/slice scans remain exploratory and unadjusted. The artifact does not claim a simultaneous confidence band, significance after scanning many periods, causal attribution, or proof of distribution drift. Use the [raw-data cohort diagnostic workflow](degradation.md) when you have both cohorts and need its explicit resampling assumptions or feature-distribution summaries.

## Critical slices and source diagnostics

The artifact retains already-approved slice metrics for each period and compares slice values/prevalence with the reference. It identifies new/missing groups, ranks the largest observed degradations, and marks explicitly named critical slices. `--prevalence-threshold` defaults to an absolute proportion change of 0.1. Missing groups have no invented performance estimate.

This supports recurring site, batch, assay, and other configured subgroup diagnostics using aggregate receipts. When a source receipt includes a `degradation-summary/v1` cohort analysis, the period records that the analysis is available in its source receipt; the source digest identifies that evidence. Cross-period feature-distribution tests or joint resampling results are not fabricated from marginal summaries.

## Recurring quality decisions

Pass `--quality-policy quality.yaml` to apply the existing [quality gate](quality_gates.md) to every source receipt. Without it, an included source gate's status is retained when available. Requirements needing private evidence that was not released return `investigate`.

The CLI exit status follows the **latest** period's quality result: `1` for fail, `2` for investigate, and `0` for pass or successful construction without a declared quality gate. Earlier failures remain in the artifact and do not permanently fail a recovered model's current check. Read the reported quality status; exit zero without a policy does not establish model acceptability.

## Public release

The local artifact is written by default. To export the series and its Markdown summary, approve exact series/model identities, all collection times, and any complete slice partition:

```yaml
schema_version: release-policy/v1
id: reviewed-assay-series
enabled: true
require_privacy_audit: false
include_protocol: true
include_quality_gate: true
include_source_receipts: true
public_series:
  id: local-assay-study
  revision: v1
public_models:
  - id: published-model
    revision: weights-v2
public_times:
  - '2026-01-01'
  - '2026-04-01'
  - '2026-08-01'
slices:
  site: [lab-a, lab-b, lab-c]
```

```sh
plb trend jan.shareable.json apr.shareable.json aug.shareable.json --time 2026-01-01 --time 2026-04-01 --time 2026-08-01 --series local-assay-study@v1 --model published-model@weights-v2 --release-policy series-release.yaml --out reports/assay-trend.json
plb verify reports/assay-trend.shareable.json
```

The example assumes every source already passed its own reviewed release policy. Set the series policy's audit requirements to match your study; the new artifact does not reconstruct withheld audit evidence. A series policy requiring fresh privacy/design evidence remains blocked when that evidence is unavailable.

Every period must satisfy the new sample floor and any known independent-unit floor. Approved slices must cover a complete disjoint partition in each period; their observed labels can vary within the approved union. Small groups or incomplete partitions block release. Omit `slices` to withhold all slice trajectories and critical labels. Collection times, study membership, and source hashes can themselves be sensitive; `include_source_receipts` explicitly approves publishing hashes of already-shareable source receipts, never raw dataset hashes.

The exporter recomputes changes, prevalence, rankings, and interval bounds from approved numeric evidence; caller-supplied change fields and unknown metadata are discarded. Paths, receipt IDs, local policy/context, and unapproved labels are excluded. Failed reruns remove stale public JSON and Markdown outputs. The workflow stays local and requires no account, telemetry, or hosted monitoring service.

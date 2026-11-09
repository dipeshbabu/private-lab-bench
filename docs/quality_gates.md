---
icon: material/filter-check-outline
---

# Model-quality gates

Quality gates apply explicit user thresholds to evaluation evidence. They do not
authorize disclosure and do not replace the underlying metrics or intervals.

```sh
plb run configs/tabular_eval.yaml
plb gate reports/tabular_demo_receipt.json --policy examples/quality_policy.yaml --out reports/quality_decision.json
```

The `quality-policy/v1` file supports overall metric limits, confidence-bound
limits, candidate-versus-baseline regression allowances, paired practical
improvement, worst-slice limits, named critical slices, and privacy requirements.
For config-driven decisions, put the same mapping under `quality_gate` in the
evaluation YAML. Reports and local receipts record the policy and every rule.

```yaml
schema_version: quality-policy/v1
metric_basis: clean
min_samples: 20
metric:
  rmse:
    max: 0.30
    max_ci_upper: 0.35
baseline:
  metric: rmse
  allow_relative_regression: 0.05
  allow_absolute_regression: 0.02
slices:
  worst_rmse_max: 0.45
  critical:
    external:
      column: site
      value: external
      metric: rmse
      max: 0.38
```

Each metric accepts `min`, `max`, `min_ci_lower`, and `max_ci_upper`. Confidence
requirements need an evaluated interval for the same metric basis. A suppressed,
missing, undefined, or underpowered result is `investigate`; it never silently
passes. A definite failed rule takes precedence over an inconclusive rule.

Baseline regressions respect metric direction: increases in RMSE or decreases in
AUROC count as degradation. Relative regression divides by the absolute baseline
value. A zero/undefined baseline is inconclusive for a relative rule; use an
absolute allowance when appropriate. This is a threshold check, not a paired
significance test.

For a paired-comparison artifact, use `comparison: {min_improvement: 0.01,
require_confident: true}` to require the joint interval's lower bound to meet a
practical improvement threshold. Without `require_confident`, the rule checks the
point estimate. The comparison must retain paired alignment and inference from
the normal comparison workflow.

Worst-slice rules inspect every available configured group. If any group is
suppressed or undefined, the rule is inconclusive. Critical rules require explicit
column/value selectors; the tool does not guess how an alias maps to private
metadata. `privacy` can require an empirical audit, an upstream release gate, or a
maximum recorded risk level. Missing evidence remains inconclusive. An upstream
gate passing is not a claim that an artifact has been published.

Clean metrics are the default basis. A perturbed shareable receipt cannot satisfy
clean-metric rules. Selecting `metric_basis: reported` explicitly applies rules to
released values, and clean-data intervals/slices are not reused for noisy values.

CLI exit codes are **0 = pass**, **1 = fail**, **2 = investigate/invalid evidence**.
`plb run` returns the gate code when a quality policy is configured; local
evaluation artifacts remain available for all outcomes. `plb gate` checks source
integrity, optionally using `--trust-store` and `--require-trusted-signer`, and
preserves the source artifact.

Gate details and private slice selectors stay local. An export policy may opt in
with `include_quality_gate: true` to release only the gate schema and status, not
thresholds, private labels, or hidden exact scores. This extra aggregate disclosure
still needs the normal release review. A recipient can rerun a policy against
disclosed evidence; rules needing withheld evidence return `investigate`.

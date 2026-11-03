# 5-minute quickstart

Start with your own prediction CSV, or try a bundled synthetic pack.

## 1. Install

Install the current release in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install private-lab-bench==0.1.3
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. The [installation guide](install.md)
covers optional dependencies and development installs. You can also run the
[quickstart in Colab](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/v0.1.3/examples/notebooks/quickstart.ipynb).

## 2. Evaluate your own model outputs

Export a local CSV such as:

```csv
sample_id,target,prediction,site
s01,0.12,0.14,lab-a
s02,0.20,0.23,lab-a
s03,0.33,0.31,lab-b
```

Then run:

```bash
plb evaluate predictions.csv --slice site
plb verify reports/evaluation/evaluation_receipt.json
```

The summary shows sample count, primary metric, available uncertainty, baseline improvement when supplied, worst eligible slice, release status, and receipt path. Full details stay in the local report and receipt. This three-row illustration is too small for a default confidence interval (at least 20 rows) or slices (at least five rows per group); the output says so.

Default primary metrics are RMSE for regression, AUROC for binary classification, and macro AUROC for multiclass probabilities. Use `--primary-metric mae` for a different supported choice. No model-quality threshold is invented for you. The default bootstrap assumes independent rows for regression and resamples within target classes for classification; review these assumptions for dependent scientific observations.

## 3. Resolve ambiguity explicitly

Conventional `sample_id`, `target`, and `prediction` columns are detected when unambiguous. Select other columns explicitly:

```bash
plb evaluate outputs.csv --sample-id-column record_id \
  --target observed --prediction-column predicted --task-type regression
```

Non-integer continuous targets with more than two values can infer regression. Binary-looking, integer-valued, or categorical targets require an explicit choice. For binary probabilities:

```bash
plb evaluate probabilities.csv --task-type classification
plb evaluate named_classes.csv --task-type classification \
  --class-labels healthy diseased
```

Numeric labels `0` and `1` use `1` as positive after classification is selected. Named labels require ordered negative/positive classes: predictions represent the probability of the second label. Multiclass evaluation requires ordered `--prediction-columns p_a p_b p_c --class-labels a b c`. Missing labels, duplicate IDs, invalid probabilities, and ambiguous columns produce actionable errors.

Repeat `--slice site --slice batch` for subgroup evaluation. Add `--baseline-column baseline_prediction` for a same-table baseline, or `--quality-policy quality.yaml` for explicit pass/fail/investigate rules. See [quality gates](quality_gates.md).

## 4. Keep a reproducible configuration

```bash
plb init predictions.csv --slice site --out evaluation.yaml
plb run evaluation.yaml
plb list-protocols
plb evaluate predictions.csv --protocol plb://generic/regression@1.0.0
```

`init` writes local paths and settings without copying dataset rows. With a protocol, it also pins the exact digest so later changes to a local definition are rejected. Existing configs require `--force` to overwrite. Evaluation also keeps a generated config under its output directory; use `--output-dir reports/another_run` to retain separate runs. Manually authored configs in that directory are protected. Exact [protocol versions](protocols.md) bind scientific settings and reject contradictory overrides.

## 5. Compare and exchange results

```bash
plb compare candidate.csv baseline.csv
```

Conventional CSVs enter paired comparison directly. The same ambiguity rules apply; add `--task-type` or column flags as needed. Paired comparison requires exactly matching sample IDs and targets. See [paired comparison](paired_comparison.md) for practical thresholds and uncertainty.

Evaluation stays local by default. Public aggregate receipts require a reviewed `--release-policy release.yaml`; blocked export leaves a local receipt and release audit. A quality-gate pass does not authorize publication. See [privacy](privacy.md) and [cross-site aggregation](aggregation.md) before exchanging results.

To try a complete synthetic pack with a reviewed demonstration release policy:

```bash
plb run-pack community-tabular-regression@1.0.0
plb verify reports/benchmark_packs/tabular_regression_receipt.shareable.json
```

See [Prediction tables](prediction_tables.md) for multiclass probabilities, metadata, and slice rules.

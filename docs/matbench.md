# Matbench materials evaluation

Evaluate external predictions on seven pinned [Matbench](https://github.com/materialsproject/matbench) tasks while preserving official row identities, units, and five-fold validation definitions. Material features remain the responsibility of the model and upstream tooling; PLB scores prediction tables and generates receipts.

| Task | Input type | Records | Official primary metric | Target unit | Protocol |
| --- | --- | ---: | --- | --- | --- |
| `matbench_steels` | Composition | 312 | MAE | MPa | `plb://matbench/steels@1.0.0` |
| `matbench_expt_is_metal` | Composition | 4,921 | Probability ROC-AUC | Binary false/true | `plb://matbench/expt-is-metal@1.0.0` |
| `matbench_jdft2d` | Structure | 636 | MAE | meV/atom | `plb://matbench/jdft2d@1.0.0` |
| `matbench_expt_gap` | Composition | 4,604 | MAE | eV | `plb://matbench/expt-gap@1.0.0` |
| `matbench_glass` | Composition | 5,680 | Probability ROC-AUC | Binary false/true | `plb://matbench/glass@1.0.0` |
| `matbench_phonons` | Structure | 1,265 | MAE | 1/cm | `plb://matbench/phonons@1.0.0` |
| `matbench_dielectric` | Structure | 4,764 | MAE | Dimensionless refractive index | `plb://matbench/dielectric@1.0.0` |

These definitions come from the pinned [upstream task metadata](https://github.com/materialsproject/matbench/blob/35f88110a51adf817a53515780d99fc34f614bf8/matbench/matbench_v0.1_dataset_metadata.json). Unsupported tasks/metrics fail explicitly; this initial subset does not claim full-suite coverage.

## Prepare and evaluate

Download the public data and official split metadata explicitly:

```sh
plb matbench-prepare --dataset matbench_steels --cache-dir outputs/matbench --download --out outputs/steel-predictions.csv
```

The template contains `fold,sample_id,prediction`, with one record per official held-out observation across all five folds. Targets and material features are excluded. Train each model on the corresponding official training fold using upstream tooling, then fill its test predictions. Row order can vary; fold membership and stable Matbench `mbid` values must match exactly.

```sh
plb matbench-evaluate outputs/steel-predictions.csv --dataset matbench_steels --cache-dir outputs/matbench --output-dir reports/steel-model-v1
plb verify reports/steel-model-v1/matbench_result.json
plb verify reports/steel-model-v1/fold-0/evaluation_receipt.json
```

Provide a fresh output directory. `--prediction-column` supports another score column name. All five official test folds are required: missing folds, reassigned records, duplicate/missing IDs, extra columns, nonfinite predictions, or supplied targets that disagree with the official cache fail. Classification probabilities denote class `1`/true (metallicity or glass formation, depending on the task) and must lie in `[0,1]`.

The adapter verifies SHA-256 hashes for the exact compressed datasets and official fold file before parsing. It never regenerates splits, deduplicates observations, drops difficult rows, or decodes structure objects. Cached label/fold scoring uses ordinary Python/NumPy/Pandas without importing materials libraries. Modified/private tables belong in ordinary `plb evaluate`, rather than receiving official Matbench snapshot identity.

## Metric and fold semantics

The reference is upstream commit `35f88110a51adf817a53515780d99fc34f614bf8`. Its [scorer](https://github.com/materialsproject/matbench/blob/35f88110a51adf817a53515780d99fc34f614bf8/matbench/data_ops.py) computes ROC-AUC from original probability scores. The upstream repository documents that historical `matbench_v0.1` classification leaderboard scores used thresholded predictions and therefore differ from corrected probability ROC-AUC. This integration follows the **pinned corrected scorer**; it does not claim numerical equivalence to those historical classification entries. PyPI's older `matbench==0.6` package alone is not an adequate scorer-version identifier.

Each fold produces an ordinary local `evaluation-receipt/v1` identifying task, snapshot, fold, protocol digest, and score. `matbench-evaluation/v1` then records all five scores and the [official task statistics](https://github.com/materialsproject/matbench/blob/35f88110a51adf817a53515780d99fc34f614bf8/matbench/task.py): unweighted mean, population standard deviation of the five scores, minimum, and maximum. Unequal fold sizes do not change the weighting. Flattening test predictions into one pooled MAE/AUROC is not the benchmark aggregation procedure.

Fold standard deviation describes those five evaluations. It is not a test-population confidence interval, and overlapping training sets are not asserted independent. These point-score protocols disable bootstrap uncertainty deliberately and select the official primary metric. Target units are part of regression protocol definitions and therefore their canonical digests.

## Optional materials tooling and upstream parity

The optional extra supplies [Matminer](https://hackingmaterials.lbl.gov/matminer/) for retrieving/featurizing upstream composition and structure inputs:

```sh
python -m pip install -e '.[matbench]'
```

For a reference comparison, use a separate Python 3.12 environment. Install the optional materials/dev tools, fetch the exact reviewed upstream package files, and install that local reference:

```sh
python -m pip install -e '.[dev,matbench]'
python scripts/fetch_matbench_reference.py --output-dir outputs/matbench-reference
python -m pip install --no-deps --force-reinstall outputs/matbench-reference
python scripts/validate_matbench.py --download --cache-dir outputs/matbench --output-dir outputs/matbench-validation
```

The fetcher verifies the manifest's pinned file hashes and keeps the upstream license. It fetches the small framework package and its fold definitions, avoiding the repository's submissions archive. The reference's version remains `0.6`, so its Git commit and scorer hash are recorded explicitly. The separate Python 3.12 CI job checks fixed-prediction agreement against this actual reference without downloading benchmark data in normal tests.

The opt-in real-data script obtains train/test frames through Matbench's own loader, checks exact IDs and labels, records every fold through its API, and compares PLB's scores **and task aggregation** at absolute tolerance `1e-12`. It uses a training-fold mean baseline and seeded fixed-random predictions as reproducibility controls, not competitive models. The low-probability classification control exercises the corrected AUC behavior.

The checked-in [aggregate verification record](https://github.com/dipeshbabu/private-lab-bench/blob/main/examples/matbench/verification.json) covers 70 real fold evaluations across seven tasks and two controls, with verified receipts, source hashes, and exact dependency versions. It contains no dataset rows, structures, compositions, or prediction tables.

## Release approved aggregate results

Local fold receipts remain local. A reviewed `--release-policy` can export the aggregate task result and Markdown table:

```yaml
schema_version: release-policy/v1
id: reviewed-steel-evaluation
enabled: true
require_privacy_audit: false
include_protocol: true
public_benchmark:
  id: matbench_steels
  version: matbench-v0.1-35f88110
  suite: matbench
  domain: materials
  protocol: prediction-table/v1
```

This example assumes the owner reviewed aggregate release for the study; configure evidence requirements appropriately. Publication requires exact task/snapshot/protocol identities and sufficient counts in **every fold**. The exporter recomputes statistics from valid official fold scores and excludes paths, model predictions, local receipt hashes, and unknown metadata. Public test data does not automatically authorize disclosure of a private model's prediction artifacts. Failed reruns remove stale public results.

## Reuse privately and cite upstream

Use the same scoring contract on an analogous private materials dataset:

```sh
plb evaluate private-steel-predictions.csv --protocol plb://matbench/steels@1.0.0 --output-dir reports/private-steel
```

Targets must use the declared MPa unit; no implicit conversion is performed. This selects the metric/unit contract, not official Matbench dataset identity or official five-fold membership. Derive a new versioned protocol for another target unit, justified uncertainty method, or study design.

Matbench's pinned [repository license](https://github.com/materialsproject/matbench/blob/35f88110a51adf817a53515780d99fc34f614bf8/LICENSE) is MIT. Individual dataset terms are separate: review the [Matminer dataset descriptions and original references](https://hackingmaterials.lbl.gov/matminer/dataset_summary.html) before reuse/redistribution. Cite Matbench's [benchmark paper](https://doi.org/10.1038/s41524-020-00406-3), the original steel/experimental-metallicity/JARVIS sources listed upstream, the evaluated model, and PrivateLabBench. This repository fetches upstream data instead of redistributing benchmark rows.

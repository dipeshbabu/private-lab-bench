# TDC ADMET integration

Evaluate external predictions on six official [Therapeutics Data Commons ADMET](https://tdcommons.ai/benchmark/admet_group/overview/) tasks, then carry the same metric contract into private ADMET evaluation. TDC supplies the public benchmark definitions and data. PLB verifies the cached snapshot, aligns predictions, and writes its ordinary local reports and `evaluation-receipt/v1` artifacts.

| Dataset | Task | Official metric | Train/validation pool | Fixed test records | PLB protocol |
| --- | --- | --- | ---: | ---: | --- |
| Caco2_Wang | Regression | MAE, lower is better | 728 | 182 | `plb://tdc/admet/caco2-wang@1.0.0` |
| Pgp_Broccatelli | Binary classification | ROC-AUC, higher is better | 973 | 245 | `plb://tdc/admet/pgp-broccatelli@1.0.0` |
| `ames` | classification | AUROC | 5,821 | 1,457 | `plb://tdc/admet/ames@1.0.0` |
| `herg` | classification | AUROC | 523 | 132 | `plb://tdc/admet/herg@1.0.0` |
| `lipophilicity_astrazeneca` | regression | MAE | 3,360 | 840 | `plb://tdc/admet/lipophilicity-astrazeneca@1.0.0` |
| `solubility_aqsoldb` | regression | MAE | 7,985 | 1,997 | `plb://tdc/admet/solubility-aqsoldb@1.0.0` |

This subset covers six of the ADMET group's tasks. Other datasets and metrics, including AUPRC and Spearman, are rejected by this adapter until their upstream definitions have their own tested contracts. `TDCTask` metadata and ordinary versioned protocols provide the extension boundary.

## Install the optional reference environment

Core installation can evaluate an existing official CSV cache without importing TDC. Fetching data and running the reference baseline require the optional extra. Use a **separate Python 3.11 environment**:

```sh
python -m venv .venv-tdc
# Activate .venv-tdc using your shell's usual activation command.
python -m pip install -e '.[tdc]'
```

The extra pins the tested PyTDC 0.4.1 reference loader, NumPy 1.x, a compatible Hugging Face Hub version, and setuptools with `pkg_resources`. This is a compatibility environment, not a claim that 0.4.1 is the latest TDC release. Do not combine its `rdkit-pypi` dependency with PLB's separate modern `rdkit` extra: both provide the `rdkit` import namespace. The pinned reference environment is tested in its own CI job.

## Prepare and evaluate predictions

Downloading is explicit and keeps the public benchmark cache outside tracked source:

```sh
plb tdc-prepare --dataset caco2_wang --cache-dir outputs/tdc --download --out outputs/caco2_predictions.csv
```

The template contains `sample_id,prediction`; targets and molecules are excluded. Fill every prediction, retaining the generated IDs. For PGP, provide probabilities for numeric positive class `1`, in the range zero to one. Regression predictions must be finite scalars.

```sh
plb tdc-evaluate outputs/caco2_predictions.csv --dataset caco2_wang --cache-dir outputs/tdc --output-dir reports/caco2
plb verify reports/caco2/evaluation_receipt.json
```

Use `--prediction-column` for another column name. Shuffled rows are aligned by exact generated IDs. Missing, extra, or duplicate IDs fail. ID-less predictions require `--upstream-test-order`, an explicit assertion that their order matches the upstream fixed test table. If targets are supplied, they must equal the official labels.

Generated IDs use dataset, partition, and row ordinal, bound to the pinned file hashes. Upstream `Drug_ID` and molecular strings can repeat; the adapter preserves every official measurement. The archive contains 910 Caco2 and 1,218 PGP records in total, while upstream [dataset descriptions](https://tdcommons.ai/single_pred_tasks/adme/) report 906 and 1,212 unique molecular strings. Deduplicating records would change the benchmark.

Local outputs include normalized predictions, generated YAML, provenance, reports, and a verifiable receipt. The receipt records the dataset, snapshot version, protocol ID/version/digest, selected metric, and input hashes. There is **no public export by default**. Supply a reviewed `--release-policy release.yaml` for approved aggregate export; ordinary [release rules](privacy.md) apply. Failed reevaluation removes stale shareable receipt and Markdown outputs while protecting input files and manually authored configurations.

## Split and metric semantics

The adapter verifies SHA-256 digests for the exact official `train_val.csv` and `test.csv` files from ADMET archive `4426004`, identified as `admet-4426004-bd0005246cb6`. A changed snapshot fails instead of receiving the old benchmark identity. Private or modified tables belong in ordinary `plb evaluate`.

Evaluation uses the official fixed test set. The optional baseline obtains train/validation partitions through TDC's `get_train_valid_split(seed=..., split_type="default")`, preserving its scaffold semantics. It does not resplit the test set or remove duplicate measurements. Stable row IDs identify records; they do not independently establish split independence or absence of leakage.

MAE matches TDC's `Evaluator("mae")`; PLB `auroc` matches `Evaluator("roc-auc")` with class order `[0, 1]`. TDC's group evaluator rounds displayed scores to three decimals; PLB retains full precision and compares both forms in the reference run. These protocols intentionally specify point estimates, with bootstrap uncertainty disabled. Variation across training seeds is distinct from test-population uncertainty. A new protocol version can declare a justified sampling design for another study.

Protocol runs compute the declared metric list. The protocol's primary metric is the official benchmark score; ordinary runs without a protocol retain PLB's standard task metrics.

## Reproduce the real-data parity check

From a checkout in the isolated TDC environment:

```sh
python scripts/validate_tdc_admet.py --download --cache-dir outputs/tdc --output-dir outputs/tdc-validation
```

The script trains a modest random forest on each official training split for seeds 1–5: Morgan fingerprints (radius 2, 2,048 bits), 128 trees, minimum leaf size 2, square-root feature sampling, and one CPU worker. Validation records are retained but not used to fit or tune this fixed baseline. The script compares PLB scores against the upstream raw evaluator at absolute tolerance `1e-12`, checks group rounding, and verifies every receipt. `--strategy mean` provides a cheaper constant baseline.

The checked-in [aggregate verification record](https://github.com/dipeshbabu/private-lab-bench/blob/main/examples/tdc_admet/verification.json) contains 30 real runs across six tasks and five training seeds, exact dependency versions, counts, scores, and snapshot hashes. It contains no benchmark rows or model predictions. Synthetic contract tests exercise malformed submissions without network access; the separate TDC CI job also checks fixed-prediction parity against the actual upstream evaluator. Baseline scores are reproducibility evidence, not a leaderboard submission or a claim of competitive performance.

## Reuse the metric contract privately

An analogous private table needs only stable IDs, targets, and predictions:

```sh
plb evaluate private_caco2.csv --protocol plb://tdc/admet/caco2-wang@1.0.0 --output-dir reports/private-caco2
```

For binary data, use the PGP protocol and numeric labels `0,1`. This identifies the evaluation rules; it does not identify private observations as official TDC benchmark data. Use a separately versioned local protocol when changing metrics, uncertainty, slices, or scientific requirements. See [evaluation protocols](protocols.md) and [evaluation-design audits](evaluation_design.md).

## Licensing and citation

The [TDC code](https://github.com/mims-harvard/TDC) is MIT licensed. That code license does not establish the terms for every constituent dataset. Data is fetched from the upstream workflow, never redistributed in this repository. Review the [ADMET benchmark documentation](https://tdcommons.ai/benchmark/admet_group/overview/), [upstream archive](https://doi.org/10.7910/DVN/21LKWG), and each dataset's original source before reuse or redistribution. This integration makes no blanket data-license claim.

Cite the TDC paper and the original dataset sources specified by TDC. The official repository provides its current citation; the [Caco2 benchmark page](https://tdcommons.ai/benchmark/admet_group/caco2_wang/) documents its task and source. Cite PrivateLabBench separately when using its evaluation artifacts.

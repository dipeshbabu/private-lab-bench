# ProteinGym DMS substitution evaluation

Evaluate mutation-effect scores within each assay, then summarize the selected assays using ProteinGym's protein/function weighting. This integration supports twelve pinned assays from the public v1.3 substitution archive. It does not pool mutations from unrelated assays or present a subset as the full 217-assay leaderboard.

The [pinned upstream reference](https://github.com/OATML-Markslab/ProteinGym/blob/144fe22b07dfaeec2b366f2346203a9838a55b4c/reference_files/DMS_substitutions.csv) supplies assay IDs, UniProt IDs, functional categories, taxa, and expected variant counts:

| Assay | Protein | Category | Variants |
| --- | --- | --- | ---: |
| `BLAT_ECOLX_Stiffler_2015` | BLAT_ECOLX | OrganismalFitness | 4,996 |
| `RL40A_YEAST_Mavor_2016` | RL40A_YEAST | OrganismalFitness | 1,253 |
| `RL40A_YEAST_Roscoe_2013` | RL40A_YEAST | OrganismalFitness | 1,195 |
| `SPIKE_SARS2_Starr_2020_binding` | SPIKE_SARS2 | Binding | 3,802 |
| `SPIKE_SARS2_Starr_2020_expression` | SPIKE_SARS2 | Expression | 3,798 |
| `UBE4B_MOUSE_Starita_2013` | UBE4B_MOUSE | Activity | 899 |
| `OTU7A_HUMAN_Tsuboyama_2023_2L2D` | OTU7A_HUMAN | Stability | 635 |
| `DYR_ECOLI_Thompson_2019` | DYR_ECOLI | OrganismalFitness | 2,363 |
| `PTEN_HUMAN_Matreyek_2021` | PTEN_HUMAN | Expression | 5,083 |
| `PTEN_HUMAN_Mighell_2018` | PTEN_HUMAN | Activity | 7,260 |
| `GFP_AEQVI_Sarkisyan_2016` | GFP_AEQVI | Activity | 51,714 |
| `BRCA1_HUMAN_Findlay_2018` | BRCA1_HUMAN | OrganismalFitness | 1,837 |

`plb proteingym-list` lists the supported subset. Other assays, indels, clinical benchmarks, supervised cross-validation, and model checkpoint execution are outside this initial adapter.

## Prepare and evaluate model scores

Download the official archive and metadata explicitly, extracting only selected assays:

```sh
plb proteingym-prepare --assay RL40A_YEAST_Roscoe_2013 --cache-dir outputs/proteingym --download --out outputs/ubiquitin-predictions.csv
```

The template contains `assay,sample_id,prediction`; targets and protein sequences are excluded. Stable IDs combine the official assay ID and its exact `mutant` descriptor, preserving assay boundaries. All files are checked against pinned SHA-256 digests. Modified/private data must use the ordinary protocol instead of official snapshot identity.

```sh
plb proteingym-evaluate outputs/ubiquitin-predictions.csv --assay RL40A_YEAST_Roscoe_2013 --cache-dir outputs/proteingym --model model-x@weights-v2 --score-direction higher --output-dir reports/ubiquitin-model-x
plb verify reports/ubiquitin-model-x/proteingym_result.json
```

Repeat `--assay` to evaluate several assays. The score file must cover every selected variant exactly once. Shuffled rows align by stable ID. Native ProteinGym files containing `mutant` and a model-score column also work: for one explicitly selected assay, its namespace is supplied by the command; multiple assays require an `assay` column. Select another score column with `--prediction-column`.

Declare `--score-direction higher` when larger model scores predict greater fitness, or `lower` when lower scores do. The latter reverses the model score once before evaluation. Processed upstream `DMS_score` is already oriented toward higher fitness and is not flipped again. Provided target columns are checked against the pinned processed targets at absolute tolerance `1e-12`; they never replace the authoritative targets. Missing/duplicate IDs, incomplete assay coverage, nonfinite scores, and target mismatches fail.

Extra sequence/model columns in compatible scoring files are excluded from normalized evaluation tables. Use a fresh output directory. No model weights, remote custom code, or neural-model dependencies are downloaded by evaluation.

## Spearman and aggregation semantics

`spearman` is a first-class regression protocol metric with higher values preferred. It uses average tied ranks and matches the upstream use of `scipy.stats.spearmanr`. Constant target or model scores produce an undefined coefficient, not zero. Nonfinite scores are rejected. Ordinary regression defaults retain MAE/RMSE/R² without computing rank correlation; versioned protocols select their declared metrics explicitly.

Each assay produces a standard local `evaluation-receipt/v1` with assay/snapshot/protocol identity. Its metric is computed within that assay only. The reusable protocol `plb://proteingym/dms-substitutions-spearman@1.0.0` requires an `assay` column containing one group; mixed-assay ordinary evaluations and paired comparisons are rejected.

The aggregate artifact follows the pinned [upstream analysis](https://github.com/OATML-Markslab/ProteinGym/blob/144fe22b07dfaeec2b366f2346203a9838a55b4c/proteingym/performance_DMS_benchmarks.py):

1. Retain full-precision assay Spearman coefficients for inspection.
2. Round each assay coefficient to three decimals for aggregation, matching upstream processing.
3. Average assays within each UniProt/function pair.
4. Average proteins within each function, then average the represented functions equally.

Taxon summaries similarly average within protein/taxon before averaging proteins. The output records both raw and rounded assay coefficients and the exact aggregation rule. Undefined assay scores keep the aggregate unavailable instead of silently dropping a failed assay. The selected-subset mean is not a pooled correlation or a full ProteinGym ranking.

The benchmark preset produces point estimates without aggregate bootstrap uncertainty. Private protocols can declare justified row/cluster uncertainty and paired comparisons under a new protocol version; variants need not be independent observations. An assay/function/taxon summary does not establish causality or clinical validity.

## Optional baseline and real-data parity

The optional extra adds Biopython for the controlled BLOSUM62 substitution-sum baseline:

```sh
python -m pip install -e '.[dev,proteingym]'
python scripts/validate_proteingym.py --download --cache-dir outputs/proteingym --output-dir outputs/proteingym-validation --run-upstream-pipeline
```

The script uses BLOSUM62 substitution sums and seeded fixed-random controls. It checks every assay against the pinned upstream metric function, verifies assay receipts, and optionally runs the actual upstream analysis script with the selected reference rows and custom control-model configuration. That full reference step also runs upstream's 10,000-resample calculations and can take several minutes; only point summaries are compared. No aggregate uncertainty is copied into PLB's point-only artifact.

The checked-in [aggregate verification record](https://github.com/dipeshbabu/private-lab-bench/blob/main/examples/proteingym/verification.json) identifies the exact archive/reference/scorer hashes and dependency versions. It contains no sequences, mutation rows, or raw prediction tables. These controls test interoperability and weighting; they are not competitive protein-AI performance claims or independent researcher trials. The normal CI fixture uses synthetic data and frozen baseline values without downloading the benchmark archive.

## Approve public aggregate results

There is no public export by default. Pass `--release-policy` to approve exact benchmark/model identity and every included assay:

```yaml
schema_version: release-policy/v1
id: reviewed-protein-evaluation
enabled: true
require_privacy_audit: false
include_protocol: true
public_benchmark:
  id: proteingym-dms-substitutions
  version: proteingym-v1.3-3a837662-144fe22b
  suite: proteingym
  domain: proteins
  protocol: prediction-table/v1
public_models:
  - id: model-x
    revision: weights-v2
public_assays: [RL40A_YEAST_Roscoe_2013]
```

Configure evidence requirements for the actual study; the example assumes separate owner review for public benchmark/synthetic-control results. Every assay must satisfy the new sample floor. The exporter rebuilds metadata from the pinned registry and recomputes rounded hierarchical summaries, excluding paths, source score hashes, sequences, raw IDs, and unknown fields. Failed reevaluation clears stale public JSON and Markdown outputs.

## Use the protocol on private DMS data

Prepare a single-assay table with `sample_id,target,prediction,assay`. Orient targets and predictions so larger values mean greater fitness; the assay label may be an opaque private identifier.

```sh
plb evaluate private-dms.csv --protocol plb://proteingym/dms-substitutions-spearman@1.0.0 --output-dir reports/private-dms
```

This applies the rank-scoring contract without claiming official ProteinGym dataset identity. Run separate tables for separate assays. Private assay labels and raw sequences are excluded from public receipts unless explicitly approved under normal [release controls](privacy.md).

Cite [ProteinGym and its benchmark paper](https://github.com/OATML-Markslab/ProteinGym#reference), the original assay papers listed in its reference file, the evaluated model, and PrivateLabBench. The [upstream code license](https://github.com/OATML-Markslab/ProteinGym/blob/144fe22b07dfaeec2b366f2346203a9838a55b4c/LICENSE) is MIT; individual data/source terms are separate. Review upstream requirements before reuse or redistribution. This repository fetches processed data instead of redistributing its rows.

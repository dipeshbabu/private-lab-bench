# A scientific decision in five minutes

Try the synthetic example, evaluate your own predictions, then share only approved
evidence. No account, model training, or dataset upload is required.

## Install

```sh
python -m venv .venv
```

Activate with `source .venv/bin/activate` on macOS/Linux, or
`.venv\Scripts\Activate.ps1` in Windows PowerShell. Then:

```sh
python -m pip install private-lab-bench==0.1.6
```

The [installation guide](install.md) covers optional dependencies. The
[Colab notebook](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/main/examples/notebooks/quickstart.ipynb)
installs the same PyPI version and contains the complete synthetic example.

## 1. Try the decision

Download the project's small example script in a fresh working directory. The
following commands work in PowerShell, bash, and zsh:

```sh
python -c "from urllib.request import urlretrieve; urlretrieve('https://raw.githubusercontent.com/dipeshbabu/private-lab-bench/main/examples/first_run.py', 'first_run.py')"
python first_run.py --output-dir plb-demo
plb verify plb-demo/evaluation/evaluation_receipt.json
```

The fixture generates **160 independent simulated specimens**, with 120 measured
by instrument A and 40 by instrument B. Its candidate has an intentionally
constructed calibration bias on B. Targets and predictions are generated from a
fixed synthetic signal and separate noise; no real assay data or trained model is
downloaded. Thresholds are fixed before generation.

The actual computed result, rounded to three decimals:

| Evidence | Result | Decision |
| --- | --- | --- |
| Overall candidate / baseline MAE | 0.272 / 0.497 | Candidate improves |
| Paired MAE improvement, 95% interval | 0.225 [0.178, 0.267] | Exceeds required improvement 0.05 |
| Instrument B candidate MAE | 0.797 | Exceeds the prespecified maximum 0.50 |
| Quality gate | **fail** | Reject for instrument B despite overall improvement |

Intervals and group diagnostics are computed, not skipped for sample count.
The percentile bootstrap resamples paired independent specimens, with 1,000
resamples and a fixed test seed. The instrument mix is part of that resampling
assumption. The critical group was specified in advance; this is not a search for
the worst-looking subgroup. Floating-point results can vary slightly by environment.
Repeated compounds, patients, or batches require an appropriate
[sampling design](sampling_design.md) when you use real data.

Inspect these files under `plb-demo/`:

| File | Contents |
| --- | --- |
| `decision.json` | Computed decision, paired interval, and critical-rule evidence |
| `candidate.csv`, `baseline.csv` | Synthetic predictions with exact paired sample IDs |
| `quality.yaml`, `evaluation.yaml` | Prespecified thresholds and reproducible settings |
| `paired.md`, `paired.json` | Paired comparison and subgroup uncertainty |
| `evaluation/evaluation_receipt.json` | Local evaluation evidence |

The example exits successfully when the complete demonstration finishes. Its
deliberate **model-quality failure** is the result, not an installation error.
The normal `plb evaluate`/`plb gate` commands still return exit code 1 for a failed
quality gate. No shareable receipt is created by default.

## 2. Evaluate your own predictions

Export a CSV with `sample_id,target,prediction` and optional group columns:

```sh
plb evaluate YOUR.csv --task-type regression --slice instrument --output-dir YOUR_RESULTS
plb verify YOUR_RESULTS/evaluation_receipt.json
```

This command computes results locally and invents no acceptance thresholds. Supply
your own [quality policy](quality_gates.md) when you have scientific acceptance
criteria. The default bootstrap needs at least 20 observations; group metrics need
at least five rows per group. Small tables in the [CSV reference](prediction_tables.md)
illustrate schema, not a statistically useful experiment.

Use `--target`, `--prediction-column`, and `--sample-id-column` for other column
names. Classification needs explicit class/probability meaning; see
[prediction tables](prediction_tables.md). Save settings with:

```sh
plb init YOUR.csv --task-type regression --slice instrument --out evaluation.yaml
plb validate-config evaluation.yaml
plb run evaluation.yaml
```

Use an exact [protocol](protocols.md) when collaborators need shared metrics,
sampling assumptions, and decision criteria. For two aligned prediction files:

```sh
plb compare candidate.csv baseline.csv --target target --task-type regression --metric mae --practical-threshold 0.05
```

See [paired comparisons](paired_comparison.md) for dependent sampling and
noninferiority. The [public Caco2 case](case_study.md) adds pinned upstream parity,
a real public control, and an explicitly synthetic measurement-shift proxy.

## 3. Share approved evidence

For this generated synthetic fixture only, explicitly approve aggregate export:

```sh
python first_run.py --output-dir plb-demo-approved --share-synthetic
plb verify plb-demo-approved/evaluation/evaluation_receipt.shareable.json
```

The demo policy deliberately waives an empirical privacy audit for **fully
synthetic data**. Do not reuse that waiver for private data. A failed model-quality
rule does not by itself prohibit sharing an approved synthetic result. Disclosure
approval, scientific quality, and signatures answer different questions.

The receipt verifier checks integrity. The demo receipts are unsigned: no
authenticated signer, independently verified execution, or scientific validation
is claimed. Real collaborators can use a reviewed release policy and pinned
[signer trust](receipt_trust.md); consult the [privacy guide](privacy.md) first.

## If something fails

- **`plb` is missing:** activate the environment used for installation; try
  `python -m privatelabbench.cli --help` and `python -m pip show private-lab-bench`.
- **The script download fails:** check access to `raw.githubusercontent.com`, or
  download `examples/first_run.py` from the repository and run the saved file.
- **Output directory is not empty:** use a new `--output-dir`. Existing files are
  deliberately preserved.
- **A private CSV's interval is skipped:** check row/group counts and declared
  sampling units; do not lower thresholds merely to obtain an interval.
- **The demo's quality gate fails:** this is the expected instrument-B decision.
  An incomplete or invalid calculation exits with an error instead.

## Independent walkthroughs

Automated checks do not establish that a new researcher can complete the flow.
Independent trials remain **0/3**. The [voluntary trial guide](case_study/trial_guide.md)
records redacted setup friction, interpretation, and decision usefulness without
private datasets, contact details, or telemetry. See the
[pending findings](case_study/findings.md). No outreach or researcher feedback is
claimed by this engineering example.

# 5-minute quickstart

The fastest complete workflow uses a bundled benchmark pack.

## 1. Install

Use the source install until the first PyPI release is live:

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
pip install -e .
```

## 2. See available evaluation packs

```bash
plb list-packs
```

## 3. Run a domain-neutral regression pack

```bash
plb run-pack community-tabular-regression@1.0.0
```

The run writes a JSON/Markdown report, audit log, manifest, local receipt, shareable receipt, and receipt Markdown.

## 4. Verify the shareable receipt

```bash
plb verify reports/benchmark_packs/tabular_regression_receipt.shareable.json
```

## 5. Evaluate your own model outputs

Export a local CSV such as:

```csv
sample_id,target,prediction,site
s01,0.12,0.14,lab-a
s02,0.20,0.23,lab-a
s03,0.33,0.31,lab-b
```

Then run:

```bash
plb eval-predictions predictions.csv \
  --target target \
  --prediction-column prediction \
  --sample-id-column sample_id \
  --require-sample-id \
  --slice-columns site
```

See [Prediction tables](prediction_tables.md) for multiclass probabilities, metadata, and slice rules.

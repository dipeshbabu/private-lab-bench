# PrivateLabBench

**Local-first evaluation for scientific machine learning on private data.**

PrivateLabBench evaluates model predictions on datasets that cannot be uploaded to a public benchmark service. Runs stay local and produce metrics, slice diagnostics, privacy-audit summaries, verifiable manifests, and evaluation receipts.

> Benchmark locally. Share evaluation artifacts, not raw data.

## Start here

- [Install](install.md)
- [5-minute quickstart](quickstart.md)
- [Prediction-table protocol](prediction_tables.md)
- [Evaluation receipts](evaluation_receipts.md)
- [Community benchmark packs](benchmark_packs.md)
- [Privacy guarantees and audits](privacy.md)

## Core workflow

```text
local prediction table
        ↓
      task
        ↓
metrics + slices + privacy audits
        ↓
report + manifest
        ↓
local receipt + shareable receipt
```

The core does not require a hosted service, account, model framework, or private-data upload.

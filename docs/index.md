---
icon: material/home-outline
---

# PrivateLabBench

Evaluate scientific model predictions locally, compare candidates with a baseline,
and decide whether they meet your scientific requirements. Keep private rows in
your environment; share reviewed aggregate evidence when disclosure is approved.

## Choose your starting point

| Journey | Start here |
| --- | --- |
| Try a scientific decision | [Synthetic calibration walkthrough](quickstart.md): a better overall model fails a required instrument group |
| Evaluate your own private data | [Prediction tables](prediction_tables.md), [paired comparisons](paired_comparison.md), and [quality gates](quality_gates.md) |
| Share approved evidence | [Evaluation receipts](evaluation_receipts.md), [release policy](privacy.md), and [signer trust](receipt_trust.md) |

Install the [current PyPI release](install.md), or open the
[Colab notebook](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/main/examples/notebooks/quickstart.ipynb).
Evaluation needs no account, hosted service, training framework, or data upload.

## Follow a scientific case

The [Caco2 model-selection study](case_study.md) begins with a real public TDC ADMET
control, reproduces upstream scoring, and examines an explicitly synthetic
measurement-shift proxy. It shows what an overall benchmark score can miss.
Additional guides cover [TDC](tdc_admet.md), [Matbench](matbench.md), and
[ProteinGym](proteingym.md), with versioned protocols and pinned upstream checks.

## Interpret the evidence

Uncertainty depends on declared sampling assumptions. Quality gates check chosen
scientific requirements. Release policies govern disclosure. Verification can
establish integrity or an authenticated signer statement; it does not independently
establish execution or scientific validity. [Concepts](concepts.md) explains these
boundaries before you explore the optional [privacy](privacy.md) and
[sandbox](sandbox.md) modules.

Independent researcher trials remain [pending](case_study/findings.md), at 0/3.

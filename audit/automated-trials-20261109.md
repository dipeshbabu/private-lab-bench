# Local automated trials — November 9, 2026

These are separately executed automated engineering trials, with plans saved
before model outcomes, fresh environments and independent metric implementations.
They share this project, machine and coordinating assistant. No human researcher
participated, and no independent privacy/sandbox audit was performed. The
[researcher trial count](../docs/case_study/findings.md) remains **0/3**.

The baseline was source commit
`8fc867eeadb5f52f1f04b1d73383c22671ecc36a`, package tree
`5e4e6589811fbdc01d194aaaf5c770d4da0fb0f5`. Three workers installed a local
development wheel with metadata version 0.1.6 and SHA-256
`d470fcf19ec1352614886de4091242a3fd4132b8e961e37c2ea5e05eb7095c5e`.
This is not the published PyPI 0.1.6 artifact. All 129 packaged files were checked
against the frozen Git source; Windows CRLF conversion is recorded separately.
The native GPU follow-up initially used the same frozen source through an
editable install, then repeated scoring with the verified development wheel.

## Public-data evaluation

| Trial | Prespecified setup | Actual outcome |
| --- | --- | --- |
| Binary classification | UCI Banknote Authentication; exact feature duplicates removed; 943 training and 405 holdout records; fixed scaled logistic model and training-prevalence baseline | Candidate AUROC 0.999680 versus 0.5; 95% interval [0.999064, 1]. Paired improvement 0.499680. Six independent standard-library score checks matched the library. |
| Multiclass probabilities | UCI white Wine Quality; fixed low/medium/high labels; feature-group split with 3,844 training and 1,054 holdout records, 846 holdout groups, no group overlap; fixed scaled logistic model and training-prior baseline | Log loss 0.871430 versus 1.056119; improvement 0.184688, cluster 95% interval [0.147406, 0.220729]. Accuracy 0.592030, macro-F1 0.554638. Independent log loss, accuracy and F1 matched exactly. |

Both illustrative model-quality gates passed. Thresholds are engineering examples,
not validated deployment criteria. These single-source holdouts do not establish
private-institution, prospective or clinical validity. Feature grouping is an
inferential assumption; it cannot prove independence between all observations.

The binary trial retained 51 commands, including ten initial configuration/scope
mismatches and recovery steps; 39 effective checks met their expectations. A
single-cohort aggregation was correctly refused. No second institution or site
was invented to obtain a positive aggregation result.

The multiclass trial originally passed **25 of 26 controls**. Its failed control
was important: ordinary CSV evaluation accepted a NaN probability by dropping a
row, while explicit sampling-design and paired paths rejected it. A three-row
reproduction evaluated only two rows. The failure is retained in the baseline
evidence, rather than being reclassified as a pass.

### Source attribution

- [Banknote Authentication](https://archive.ics.uci.edu/dataset/267/banknote+authentication):
  Lohweg, V. (2012), UCI Machine Learning Repository,
  [DOI 10.24432/C55P57](https://doi.org/10.24432/C55P57), CC BY 4.0.
  Official archive SHA-256:
  `1e2acd9a2085fadf3d8145c12d3d22af853320d52294a6590c2eaf75fdc05227`;
  data payload:
  `d0539aaed2139ba7a587b3e34fb345ce503ff7d5d33dbf9912d8e195ce425cb9`.
- [Wine Quality](https://archive.ics.uci.edu/dataset/186/wine+quality):
  Cortez, P., Cerdeira, A., Almeida, F., Matos, T., & Reis, J. (2009),
  UCI Machine Learning Repository,
  [DOI 10.24432/C56S3T](https://doi.org/10.24432/C56S3T), CC BY 4.0.
  Official archive SHA-256:
  `3ed56667f4b828242bd732d7d1dd7f2861e54432239d7fa63877014cbb0304d4`;
  white-wine CSV:
  `76c3f809815c17c07212622f776311faeb31e87610d52c26d87d6e361b169836`.

Only aggregate results are included here. Downloaded rows, predictions, model
parameters, signing keys and exact local logs remain outside tracked source.
This is a bounded collection of relevant primary sources, not the entire Internet.

## OpenDP and durable accounting on Windows

A fresh Python 3.12.13 environment installed the actual OpenDP 0.16.0 Windows
wheel. **74 canonical tests passed with zero skips**: 39 backend, 18 SQLite
accounting and 17 privacy-mechanism cases.

The real nondeterministic sampler then produced eight releases at epsilon 0.1
each, under one durable ledger capped at 0.8. After six charges, four separate
processes competed for the final two charges: exactly two releases succeeded and
two were refused. A new process preserved the exhausted state. Missing and corrupt
ledgers refused release; released payloads excluded exact means, rows, paths and
scope. Public-synthetic upstream constructor tests and the charged PLB release
exercise are recorded separately.

The worker saw an agent inventory containing earlier summaries after saving its
plan. That exposure is disclosed; this was not a blinded review or independent
privacy audit. These functional tests cannot certify a real private population's
contribution bounds, eligibility, ledger administration or deployment.

## Native GPU calculation followed by library scoring

The installed Windows CUDA Driver API executed one trusted synthetic affine PTX
kernel, with 64 inputs and 512 explicitly allocated device bytes. All 64 outputs
matched an independent Python Fraction oracle exactly. All CUDA calls, allocation
frees, module unload and owned-context destruction returned zero. The bounded
driver process completed in 1.412 seconds; this is not a performance benchmark.

PrivateLabBench evaluated the actual GPU-generated predictions: MAE 0, RMSE 0,
R² 1, with all 64 rows retained. The local receipt verified as integrity-only;
no shareable receipt appeared without policy. The exact outputs are a constructed
arithmetic control, not a scientific-performance claim.

The initial editable environment retained distribution metadata 0.1.0 although
its module version and executed source were 0.1.6 at the frozen commit. That
record is preserved. A separate installed-wheel scoring and verification run,
with distribution and module versions both 0.1.6, confirmed the same metrics and
row count without rerunning the kernel or fitting a model.

This establishes native trusted computation and library scoring only. It does
**not** validate untrusted-model GPU execution or Linux/gVisor isolation. The
kernel used the documented [CUDA module API](https://docs.nvidia.com/cuda/archive/12.6.0/cuda-driver-api/group__CUDA__MODULE.html),
[launch API](https://docs.nvidia.com/cuda/archive/12.6.0/cuda-driver-api/group__CUDA__EXEC.html)
and [PTX instructions](https://docs.nvidia.com/cuda/archive/11.1.0/parallel-thread-execution/index.html).
No driver, toolkit, Windows feature or container service was installed or changed.

## Corrections and retests

- Required targets, predictions/probabilities and membership split values now
  reject missing values before scoring. Legitimate exclusions remain explicit in
  the evaluation design. A fixed-source rerun used the original multiclass data,
  model and predictions without retraining: clean metrics matched exactly and
  all 15 retest checks passed, including the previously accepted NaN.
- Generic and legacy CLI verification now report unreadable, malformed and
  structurally invalid inputs cleanly. Successful output, signatures and direct
  low-level API exception behavior are preserved. Separate CLI retests leave the
  original failure logs unchanged.
- Stricter installed-wheel diagnostics exposed three pre-existing comparison
  tracebacks for incomplete/duplicate IDs and target disagreement. Rejection and
  exact alignment remain required; the CLI now reports these input errors
  without a traceback. The original diagnostic failures remain in the evidence.
- Package discovery now prunes generated auxiliary trees. A traversal regression
  fails on the prior configuration and passes with the correction. A config-only
  wheel comparison retained all 135 members, including 129 package/data payloads,
  byte-for-byte. The change affects discovery work, not library contents.
  Development tooling now requests the already-supported setuptools minimum.
  The traversal regression reads discovery settings without unrelated license
  validation and passes with setuptools 77.0.1, 77.0.3 and 84.2.1. Version 65.5.0
  lacks pruning and is below the declared build requirement; it is not reported
  as passing. The dev-extra dependency metadata changes intentionally.

Focused regressions and unchanged-input retests accompany these corrections.
The original plans and reports are preserved. CI remains required before landing
the patch; passing automated checks does not change the separate requirements in
[release readiness](../docs/release_readiness.md).

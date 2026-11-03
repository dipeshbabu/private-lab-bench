# A better model can still fail the intended use

The Caco2 case asks two different questions: does a reference forest improve on a simple training-mean baseline, and does it satisfy absolute/critical-group requirements after a controlled measurement shift? The result is **relative improvement with an unacceptable critical group**, not a deployment recommendation.

The first cohort is the real public TDC Caco2_Wang held-out test set. The second is an explicitly synthetic/private-like proxy: the same public compounds and IDs, with +0.8 added to the upstream target values for MolLogP≥3.0. It is not new unpublished laboratory data or an independent collection of compounds. The [analysis plan](case_study/analysis_plan.md) was fixed in commit `67a9385` before executing the proxy analysis; public benchmark control scores were already known.

## Observed decision

| Evaluation | Candidate MAE | Training-mean MAE | Interpretation |
| --- | ---: | ---: | --- |
| Original official public holdout | 0.433154 | 0.563877 | Public metric parity passes; candidate improves on the simple baseline |
| Synthetic measurement-shift proxy | 0.604110 | 0.734978 | Candidate still improves, but exceeds the predeclared absolute MAE limit 0.6 |
| Proxy high-logP group, 61 observations | 0.849552 | See paired/group artifacts | Exceeds the predeclared critical-group limit 0.7 |

The proxy's paired improvement is **0.130868**, with a nominal 95% cluster-bootstrap interval **[0.071865, 0.191472]**, above the practical threshold 0.02. Its overall candidate interval is **[0.540667, 0.663107]**. The high-logP group's interval is **[0.747937, 0.963676]**. These intervals condition on the declared connectivity-unit sampling assumptions; they are not guarantees of chemical independence or simultaneous coverage.

A notebook reporting only “the forest beats the mean” would miss the separate acceptance decision. The absolute quality gate fails, and the high-logP error increases from 0.339488 to 0.849552 under the controlled proxy. The unaffected group stays at 0.480374. The model predictions did not change; the experiment deliberately changed part of the measured target distribution. This demonstrates a diagnostic workflow, not discovery of a real calibration mechanism.

## Reproduce from a new environment

Use a separate **Python 3.11** environment for the pinned TDC/RDKit reference stack. Do not combine `rdkit-pypi` and the separate modern `rdkit` distribution in that environment.

```sh
git clone --branch v0.1.1 https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
python -m venv .venv-case
# Activate .venv-case with your shell's normal activation command.
python -m pip install -e '.[dev,tdc,signing]' -c docs/case_study/constraints.txt
python -m scripts.caco2_case_study --download --cache-dir outputs/tdc --output-dir outputs/caco2-case
```

This walkthrough uses the v0.1.1 source checkout because the opt-in research scripts and reference constraints are repository assets. The core framework is also installable as `private-lab-bench==0.1.1`. Data downloads stay local and come from the [TDC benchmark workflow](tdc_admet.md). Use an empty output directory for each run.

Read `outputs/caco2-case/approved/decision.md`, then verify the generated candidate receipt against **that run's own public trust store**:

```sh
plb verify outputs/caco2-case/approved/proxy-candidate.json --trust-store outputs/caco2-case/approved/trust-store.yaml --require-trusted-signer --json
plb verify outputs/caco2-case/approved/proxy-paired.json --trust-store outputs/caco2-case/approved/trust-store.yaml --require-trusted-signer --json
```

Each run creates a fresh example signing key. The checked-in reference trust store verifies the checked-in examples; it is not the key for your new run. Successful verification reports `authenticated_signer_statement` and `execution_verified: false`. It authenticates the pinned example issuer's statement, not execution, dataset truth, evaluator independence, or scientific validity.

The script's successful exit means the walkthrough completed. Its model-quality result can still be `fail`; inspect the decision page and receipts. Publication of a failing model's approved aggregate evidence is intentionally separate from accepting that model for use.

## What the run actually fixes and checks

The candidate uses 128 random-forest trees, minimum leaf size 2, square-root feature sampling, seed 1, and one CPU worker over radius-2/2,048-bit Morgan fingerprints. It fits only the 637 official seed-1 scaffold training records; the 91 validation records are unused. The full 182-record official test control matches TDC's raw MAE evaluator at tolerance `1e-12`.

The external/proxy protocol hashes the primary metric, fixed decision rules, eligibility, critical partition, and uncertainty design. It preserves repeated observations and resamples 140 molecular-connectivity units rather than treating all 182 observations as independent. Connectivity is canonicalized with stereochemistry ignored, matching the declared case unit; structurally similar nonidentical graphs may still be dependent.

The supported design audit checks the provided IDs and connectivity entities against the complete actual training reference. This run excluded zero records and found zero evaluation/training entity overlaps under those rules. Repeated entities are allowed and clustered; noisy regression labels are not treated as deterministic class labels. Passing these scoped checks does not prove no pretraining leakage, no near-neighbor/scaffold leakage, representative sampling, chronology validity, or honest execution.

Reference/current diagnostics reuse compounds and IDs, so independent-cohort delta intervals are withheld. The paired candidate/baseline interval is computed within the proxy on identical eligible records. Critical-slice scans remain exploratory. The same frozen rules are used even when the resulting quality decision is unfavorable.

## Share evidence, keep the rest local

`local/` contains SMILES, row IDs, original/proxy targets, predictions, complete audits, numeric model snapshots, and the private signing key. **Do not share or upload that directory.** The numeric forest snapshot is an audit artifact; the generic trusted scorer does not automatically load it or untrusted pickle files.

`approved/` contains only allowlisted aggregate receipts, the paired summary, the example public trust store, a decision page derived from those approved artifacts, and verification statuses. Explicit release policy approves a complete high-logP/other partition, sufficient observation/unit counts, model digests, protocol identity, and complete supported design evidence. The empirical membership-attack requirement is disabled explicitly for this public/synthetic demonstration; no differential privacy guarantee is asserted.

The [checked-in reference artifacts](https://github.com/dipeshbabu/private-lab-bench/tree/main/examples/caco2_case/approved) can be inspected without the raw test data. A collaborator can check the same protocol/model identities, aggregate decision, issuer key, and integrity hashes while the raw rows remain with the evaluator. That is the receipt's practical value beyond a copied metric cell.

The [fast CI fixture](https://github.com/dipeshbabu/private-lab-bench/blob/main/tests/test_case_study.py) exercises decision/release/trust boundaries on deterministic synthetic arrays. It does not count as a real benchmark run or an independent researcher trial. The heavy opt-in script supplies the actual public benchmark and explicitly labeled proxy evidence.

## Independent onboarding trials are still pending

No independent researcher adoption is claimed. At least three researchers uninvolved in building the package must run the walkthrough and voluntarily supply redacted usability notes. The [trial guide](case_study/trial_guide.md) and [findings record](case_study/findings.md) define what to collect. Issue #47 stays open until the trials and at least two changes responding to observed friction actually happen.

Cite TDC and the original Caco2 source as specified [upstream](https://tdcommons.ai/benchmark/admet_group/caco2_wang/), the evaluated model/protocol, and PrivateLabBench's `CITATION.cff`. This demonstration does not establish prospective, clinical, or regulatory validation.

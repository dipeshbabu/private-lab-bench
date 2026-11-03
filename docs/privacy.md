# Privacy Model and Guarantees

## Enforced export policy

Evaluation reports are local-only. Creating a shareable JSON artifact requires an
explicit `release-policy/v1` policy and successful disclosure checks. A missing,
invalid, disabled, or failed policy produces local results and a local
`*.shareable.release-audit.json`; it removes any stale shareable file.

Add a `release` section to an evaluation config, or pass a policy file to
`plb compare --release-policy release.yaml`. For example:

```yaml
release:
  schema_version: release-policy/v1
  id: reviewed-study-2026
  enabled: true
  min_samples: 20
  min_cell_size: 5
  require_privacy_audit: true
```

The standalone comparison policy file contains these fields without the outer
`release` key. Dry-run an existing local receipt with:

```sh
plb release-check reports/run_receipt.json --policy release.yaml
```

Dry runs do not export, upload, or consume a release approval. The writer also
checks local repeated-release history; a successful dry run alone does not
guarantee that a later export will be permitted.

Every upstream privacy/aggregate gate must explicitly pass when present. A missing
required audit is `not_run`; unrecognized audit evidence is `inconclusive`.
An audit passing a configured policy is empirical evidence, not proof of privacy.
Synthetic examples explicitly waive the audit requirement; review that decision
before adapting their configuration to private data.

The prediction demo's separate risk policy specifies thresholds but its table has
no membership-audit split. Its export is therefore blocked even though the demo
release policy waives a general audit requirement. Waiving that requirement never
overrides a failing upstream gate.

The exporter selects known metric and uncertainty fields. It omits local paths,
configurations, artifact names/hashes, sample identifiers, private model/project
labels, free-form metadata, and arbitrary plugin fields. Input column names are
withheld unless `include_input_schema: true` is deliberately approved. Benchmark
identity must be supplied explicitly through `public_benchmark` in the policy.
Undefined numeric metrics are represented by JSON `null`.

Slices stay local by default. A policy may approve one disjoint partition and its
exact public labels, such as `slices: {site: [a, b, c]}`. If any category is missing,
unexpected, or smaller than `min_cell_size`, the whole partition is withheld,
including its counts. Multiple overlapping partitions are rejected. Clean
intervals and clean slice metrics are withheld when overall metrics are perturbed.

The output directory's local `.plb-release-ledger.json` records approved aggregate
content by policy ID. Unchanged releases may be reproduced. Changed content under
the same ID requires a deliberate `reviewed_repeat: true` and a local
`review_reference` identifier. The override is audited and never bypasses other
gates or cell thresholds. Keep policy IDs and the ledger stable for a study;
moving directories or changing IDs starts a separate approval scope. This is a
local safeguard, not a global privacy accountant or a defense against a malicious
owner releasing additional information through other tools.

Writes use a local ledger lock and atomic file replacement. A failed export or
invalid ledger fails closed. A leftover lock from an interrupted process requires
local inspection before removal. These controls do not establish differential
privacy or guarantee that overlapping studies cannot disclose information.

PrivateLabBench separates **privacy mechanisms**, **privacy audits**, and **release policies**. These are different tools and must not be interpreted as equivalent evidence.

## 1. Exact reporting (`mode: none`)

Exact aggregate metrics are computed and reported locally. There is no privacy guarantee for the reported aggregate itself.

## 2. Heuristic metric perturbation (`mode: metric_perturbation`)

This is the successor to the historical `mode: dp` option.

```yaml
privacy:
  mode: metric_perturbation
  epsilon: 8
  sensitivity: 1
  seed: 13
```

The implementation adds independent Laplace noise to already-computed aggregate metrics using:

```text
noise_scale = user_supplied_sensitivity / epsilon_like_parameter
```

This mode is intentionally labeled:

```text
guarantee_level: heuristic_no_dp_guarantee
formal_dp: false
```

### What it can be useful for

- experimenting with privacy/utility tradeoffs;
- reducing precision of released aggregate metrics;
- testing downstream workflows that expect perturbed metrics.

### What it does NOT establish

It does not prove differential privacy because PrivateLabBench does not establish, for arbitrary model metrics:

- the global sensitivity of each released query;
- the adjacency relation over private datasets;
- clipping/bounding assumptions for every metric;
- privacy loss from releasing several statistics together;
- implementation-level numerical guarantees.

The name `epsilon` is retained for backward-compatible configuration, but in `metric_perturbation` it is an **epsilon-like noise parameter**, not a certified privacy budget.

### Legacy `mode: dp`

`mode: dp` remains accepted temporarily to avoid breaking existing configs, but it is a deprecated alias for `metric_perturbation`. It emits a warning and reports `formal_dp: false`.

## 3. Bounded-query DP primitives

PrivateLabBench includes a separate reference API for queries where sensitivity can actually be established.

### Bounded mean threat model

`BoundedMeanQuery` assumes:

- a **fixed-size dataset**;
- **replace-one adjacency**: adjacent datasets differ in one individual's record but have equal size;
- public lower/upper value bounds chosen independently of the sensitive data;
- each value is clipped locally to those bounds before aggregation.

For `n` records in `[lower, upper]`, the mean has L1 sensitivity:

```text
(upper - lower) / n
```

`release_bounded_mean` adds Laplace noise with:

```text
scale = sensitivity / epsilon
```

Under the stated adjacency/bounds assumptions, this is the standard pure epsilon-DP Laplace construction in the mathematical real-arithmetic model.

The returned metadata explicitly records:

- bounds;
- sample count;
- computed sensitivity;
- epsilon/delta;
- adjacency model;
- noise scale;
- guarantee label.

### Composition

`PrivacyBudget` tracks sequential composition. `release_bounded_means` allocates a declared total epsilon budget across several releases and refuses to exceed it.

The ledger reports both total spend and per-query spends.

### Numerical implementation note

The built-in bounded-mean mechanism is a small reference implementation using NumPy floating-point arithmetic and random sampling. It is useful for making query contracts, bounds, sensitivity, and accounting explicit.

Its serialized release excludes the exact clipped mean; that attribute is for
local inspection only. A supplied `seed` enables deterministic tests and labels
the result `none_deterministic_test_seed`, with no DP guarantee. Never publish a
known-seed result as a private release. The optional OpenDP API has no seed.

For high-assurance deployment where numerical details and end-to-end transformations must be inside a vetted privacy proof, use a specialized DP system such as **OpenDP** rather than treating this reference implementation as the final production backend.

## Optional OpenDP backend

Install the optional backend with `pip install 'private-lab-bench[opendp]'`.
It supports a bounded column mean with **public, fixed sample size and replace-one
row adjacency**. One row must represent one individual's bounded contribution.
It does not provide person-level privacy for repeated measurements without an
appropriate contribution-bounding transformation.

```python
from privatelabbench.privacy import OpenDPBoundedMean, PrivacyBudget

# Choose these values from public policy, before inspecting the private data.
budget = PrivacyBudget(epsilon_limit=1.0)
query = OpenDPBoundedMean(
    name="public-normalized-score", lower=0.0, upper=1.0,
    public_size=3, epsilon=0.5,
)
result = query.release([0.1, 0.5, 1.2], budget=budget)
print(result.as_dict())  # noisy value and public query/backend metadata only
# Reuse this SAME budget for another release about the protected population.
```

The complete chain uses OpenDP's clamp, mean, and Laplace constructors. It checks
the upstream privacy map at symmetric distance **2**, corresponding to replacing
one row. Calibration uses the upstream numerical sensitivity bound, including
floating-point effects. OpenDP supplies the randomness; this API has no seed and
does not fall back to NumPy if the optional dependency is missing.

The ledger rejects nonfinite spends and compares the exact binary floating-point
spends without absolute slack. Usage rounds upward and remaining budget rounds
downward. Boundary allocations may need headroom: `0.1 + 0.2` exceeds the binary
float `0.3`, so that combination is rejected. Batch reference allocations are
normalized exactly and rounded down. A spend is charged before sampling, including when sampling
fails. This ledger is **in memory and sequential**: retain it for every query on
the population. Applications must provide durable accounting and synchronization
across restarts, processes, exports, and other systems. Starting a new ledger does
not reset a population's actual privacy loss.

The result excludes exact means, rows, IDs, file paths, and input hashes. Bounds,
size, query names, epsilon, the choice of queries, and the decision to publish must
all be public and independent of private values. Keep validation errors and local
diagnostics private. Publishing exact evaluation receipts beside a DP mean can
invalidate the intended protection; this API does not convert existing reports
or release policies into an end-to-end DP pipeline.

The supported backend line is OpenDP 0.16. Its constructors currently require the
upstream `contrib` feature, which this backend explicitly enables. OpenDP's
[mean guide](https://docs.opendp.org/en/v0.16.0/api/user-guide/transformations/aggregation-mean.html)
and [Laplace proof](https://docs.opendp.org/en/v0.16.0/proofs/rust/src/measurements/noise/distribution/laplace/make_laplace.pdf)
describe the primitives and their assumptions. Use this specialized backend for
its numerical mechanisms and checked maps; this wrapper has not received an
independent privacy/security audit, and enabling an upstream feature does not
certify the surrounding application.

## 4. Privacy attacks are empirical audits, not guarantees

The built-in loss-threshold membership-inference attack is registered as:

```text
loss-threshold-membership-inference
baseline: true
evidence_level: empirical_audit
guarantee: none
```

A high attack score can identify a meaningful leakage signal. A low attack score does **not** prove privacy, differential privacy, or resistance to stronger attacks.

The attack registry exists so the community can add stronger audits without changing the meaning of any formal privacy mechanism.

## 5. Release policies

Privacy-risk gates and minimum-client/sample release guards are policy decisions over observed metadata. They can block sharing when evidence is insufficient or risky.

They are not cryptographic or differential-privacy guarantees.

## Safe interpretation checklist

Before describing a PrivateLabBench output as differentially private, verify all of the following:

1. The release was produced by an explicitly bounded formal query API, not `metric_perturbation`.
2. The adjacency model matches the intended privacy unit.
3. Bounds are public/non-sensitive and valid for the problem.
4. The reported sensitivity follows from that query and adjacency model.
5. The privacy budget includes all released DP queries under the relevant composition rule.
6. The implementation/backend is appropriate for the assurance level required by the application.

If any item is missing, describe the output as an exact aggregate, heuristic perturbation, empirical privacy audit, or policy gate as appropriate—not as a formal DP guarantee.

# Privacy Model and Guarantees

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

For high-assurance deployment where numerical details and end-to-end transformations must be inside a vetted privacy proof, use a specialized DP system such as **OpenDP** rather than treating this reference implementation as the final production backend.

## OpenDP integration decision

OpenDP's architecture matches the direction of the formal API:

- transformations establish domains/metrics and query sensitivity;
- measurements such as Laplace consume a sensitivity-aware input space;
- compositor/context APIs track cumulative privacy loss;
- bounded public information is part of the query definition.

PrivateLabBench does **not** make OpenDP a mandatory dependency yet. The current community core first stabilizes task/query contracts and keeps the default install light. A future optional backend can translate supported bounded queries into OpenDP measurements and composition without changing the public receipt or task schemas.

This is deliberately different from wrapping arbitrary already-computed metrics with OpenDP noise: a DP library cannot recover a valid sensitivity proof that the caller never specified.

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

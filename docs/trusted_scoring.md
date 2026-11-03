# Trusted local model scoring

`plb score` runs an explicitly approved, pinned local numeric model and writes a local prediction table. An opt-in pipeline then uses the ordinary evaluator, external-validation profile, and release gate. No private inputs are sent to a model developer or an online evaluator.

**This is trusted in-process execution, with no security sandbox.** Review the model, installed Python environment, and dependencies before approving them. The first implementation accepts only a constrained numeric JSON linear model through the built-in `plb.linear-json@1.0.0` adapter. It rejects pickle, executable submissions, arbitrary module names, remote model URLs, and untrusted execution requests. It performs no network download or remote-code loading.

## Run the controlled example

The checkout includes an illustrative solubility formula and synthetic observations. The coefficients are invented to demonstrate the contract; this is not a fitted or validated scientific model.

```sh
plb score --model examples/trusted_scoring/manifest.yaml --data examples/trusted_scoring/inputs.csv --units examples/trusted_scoring/units.yaml --data-version synthetic-v1 --output outputs/scored-predictions.csv
```

The fresh CSV contains stable `sample_id,prediction` columns. Feature values and targets are excluded. The adjacent `.score.json` file records local model/manifest/input/prediction digests, schema and units, adapter version, task, counts, and the absence of isolation. Both files remain local. Existing prediction or provenance files are preserved; choose fresh paths for another run.

Add an explicit target and protocol to evaluate locally:

```sh
plb score --model examples/trusted_scoring/manifest.yaml --data examples/trusted_scoring/inputs.csv --units examples/trusted_scoring/units.yaml --data-version synthetic-v1 --output outputs/scored-evaluation-input.csv --target target --protocol plb://generic/regression@1.0.0 --evaluate-output-dir reports/scored-reference
plb verify reports/scored-reference/evaluation_receipt.json
```

This explicitly copies the declared target into the local evaluation table. The report directory must be empty. A versioned prediction protocol with matching task and class order is required. The default external-validation context declares undisclosed dataset visibility, unknown training overlap, and undisclosed evaluator relationship. Supply `--validation-profile profile.yaml` to describe the actual relationship/provenance; its model identity must exactly match the scored model.

No shareable receipt is created by default. A reviewed `--release-policy release.yaml` goes through the [central release boundary](privacy.md), including its sample, audit, and repeated-query rules. [External-validation metadata](external_validation.md) needs exact `public_validation` approval. Scoring features, inference logs, model provenance text, private IDs, and paths are excluded from public artifacts. Failed pipelines clear previous public receipt/Markdown outputs while preserving colliding inputs; local predictions can remain for inspection.

## Review and pin the manifest

`model-manifest/v1` declares:

- `trust: approved_local`, acknowledging trust in the artifact, adapter, and runtime;
- model ID/revision, actual SHA-256, optional paper/citation, and a local artifact path with the same digest;
- the exact adapter ID/version and `numeric-json/v1` format;
- ordered feature names, `float64` dtype, and units;
- a stable sample-ID column and optional expected input dataset version;
- preprocessing/postprocessing versions and reject-missing semantics;
- deterministic inference and declared input/output/network permissions.

The [reference manifest](https://github.com/dipeshbabu/private-lab-bench/blob/main/examples/trusted_scoring/manifest.yaml) is runnable without model training or chemistry dependencies. Model bytes are preserved across checkouts so its reviewed digest is stable. Units are supplied separately as a YAML mapping of every feature name to its actual unit. A label asserts the supplied data's units; PLB cannot infer the physical truth of those labels. There is no implicit conversion.

Feature values are selected in manifest order, even if CSV columns are reordered. The JSON artifact must contain the exact same ordered `feature_names`, finite `coefficients`, and scalar `intercept`, with schema `linear-model/v1`. `identity/v1` applies the frozen linear formula. `standardize/v1` additionally requires frozen training `mean` and positive `scale` arrays; no statistics are learned from evaluation data.

Regression uses identity output with no class labels. Binary classification requires `sigmoid/v1` and ordered labels `['0', '1']`; output denotes the probability of class `1`. A stable sigmoid handles extreme logits. Missing/duplicate IDs, absent features, missing/nonfinite values, wrong units/version/digest/order, incomplete outputs, and invalid probabilities fail before the prediction table is written. Optional targets must be separate finite numeric values; binary targets must be zero/one.

The reference scorer bounds artifact size at 8 MiB, input CSV size at 64 MiB, and the feature matrix at 20 million values. These are implementation limits, not process isolation or enforceable CPU/memory quotas. Deterministic operations use frozen parameters; bit-level results can still depend on numerical libraries/hardware, whose environment should be recorded for a study.

## Adapter and future execution boundary

`TrustedModelAdapter` exposes the versioned `trusted-model-adapter/v1` interface: load approved artifact bytes, then map an explicitly ordered numeric matrix to one prediction per observation. PLB owns ID alignment, schema/unit/digest checks, local provenance, and evaluation. The current dispatcher accepts the reviewed built-in adapter only. It does not auto-discover or import a Python module named in a manifest.

A future approved adapter remains trusted code with process access. Untrusted submitted models require a separate, independently reviewed executor that enforces filesystem isolation, egress denial, resource limits, and a restricted output channel, with security testing. Those controls are not implemented here. An `untrusted_isolated` request is rejected rather than dispatched to the trusted interface.

## Hidden benchmark choices

Prediction submissions require that participants have approved access to the model inputs. If the inputs must remain hidden, the benchmark owner must execute a suitably trusted model locally, or use a separately reviewed isolated runner for untrusted models once one exists. The trusted scorer does not make an adversarial model safe to run on hidden data.

Keep local inference logs and artifacts within the lab, review aggregate release separately, and pin [trusted receipt signers](receipt_trust.md) when issuer identity matters. Model digests establish which artifact was selected; they do not prove model quality, honest provenance, or evaluator independence.

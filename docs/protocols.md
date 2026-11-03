# Evaluation protocols

An evaluation protocol fixes the scientific rules independently of a dataset. Two labs can use the same rules on different private tables and record the same ID, version, and SHA-256 digest in their receipts. A benchmark pack also ships demonstration data; a protocol contains no observations or dataset paths.

```bash
plb list-protocols
plb show-protocol plb://generic/regression@1.0.0
plb run local.yaml --protocol plb://generic/regression@1.0.0
```

The bundled regression protocol declares MAE as primary, with RMSE and R² as diagnostics. The binary protocol declares AUROC as primary, with accuracy and F1 at the runner's fixed 0.5 threshold. Both use deterministic percentile bootstrap intervals (1,000 resamples, seed 13, 95% confidence, at least 20 samples). Regression resamples rows; classification resamples within target classes. These assumptions need review for clustered or dependent scientific data. Neither protocol invents a universal quality threshold.

Your local config supplies column bindings and output paths:

```yaml
project: external-assay
protocol: plb://generic/regression@1.0.0
input:
  path: private_predictions.csv
  sample_id_column: sample_id
  target_column: observed
  prediction_column: predicted
report:
  json: reports/assay.json
  markdown: reports/assay.md
  manifest: reports/assay_manifest.json
```

`protocol` also accepts a local YAML file, resolved relative to the config. A command-line protocol path is relative to the working directory. If both are supplied, their digests must match. References always include a semantic version; there is no implicit latest version or network registry lookup.

## Frozen rules

`evaluation-protocol/v1` declares the task, task type, prediction-table schema, ordered multiclass labels, metrics and primary metric, all bootstrap settings, required and optional slice columns, slice minimum size, paired-comparison settings, optional quality policy, metric perturbation settings, release defaults, and compatible artifact versions. See the bundled YAML definitions in `privatelabbench/data/protocols/` and the distributed JSON Schema. Runtime validation also checks relationships between fields, such as metric/task compatibility.

Runs reject conflicting task, class-label order, uncertainty, quality, privacy, and slice settings. Required slices must be present; optional slices may be selected from the declared list. Comparing a slice requires the same slice definition and population interpretation. The runner may retain additional built-in diagnostic metrics; only the protocol's declared metrics form its comparison contract.

Paired-comparison rules are exposed through `resolve_protocol(reference).comparison_config()` for use with `compare_prediction_tables`. A single-table run records those rules without claiming it performed a comparison. Quality gates that require missing baseline or comparison evidence return `investigate`.

The local report and receipt retain the complete frozen definition. The identity digest uses UTF-8 JSON with sorted keys, compact separators, and no non-finite numbers, after validating and filling release count defaults. YAML formatting and mapping order do not affect identity. Treat the exact `(id, version, sha256)` tuple as the compatibility key. A matching human-readable name alone is insufficient.

## Versioning and privacy

Publish a new semantic version for every definition change, including metrics, labels, thresholds, uncertainty, slice rules, privacy defaults, or artifact compatibility. Use a major version for incompatible scientific semantics, a minor version for added compatible capabilities, and a patch version for corrections that still need a distinct identity. Discovery rejects packages that supply different definitions for the same ID and version. Independently received local definitions must also be compared by digest. A receipt's claim about a protocol does not establish that an untrusted producer executed it correctly; signer trust and scientific validity remain separate checks.

Protocol defaults always disable aggregate export. An owner can opt in through a reviewed `release-policy/v1` in the run config. That policy may raise the protocol's count thresholds but cannot lower them or waive a required audit. Public slice labels and other optional metadata still need explicit approval under the central release boundary.

Protocol identity can itself reveal the subject of private work. It is withheld from shareable artifacts unless the release policy sets `include_protocol: true`. That opt-in exports only ID, version, digest, declared metrics, and primary metric. The full rules, local paths, thresholds, and free-form configuration remain local.

When signing an approved receipt, its public protocol identity is bound automatically in the signer statement. An explicitly supplied, conflicting signer protocol is rejected.

## Third-party packages

Installed Python packages can expose a protocol object, a definition mapping, or a function returning one or an iterable through an entry point:

```toml
[project.entry-points."privatelabbench.protocols"]
assay = "my_lab.protocols:protocols"
```

```python
from importlib.resources import files
from privatelabbench.protocols import load_protocol

def protocols():
    return [load_protocol(files("my_lab").joinpath("assay.yaml"))]
```

Install only trusted provider packages: discovery imports their Python code, just like task plugins. Protocol YAML is loaded as data with `safe_load`; resolving a `plb://` reference does not download or execute remote code. A future index can map the existing ID/version to a distribution without changing the protocol schema.

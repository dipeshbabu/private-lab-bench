# Contributing to PrivateLabBench

PrivateLabBench is a community-first, local evaluation framework for scientific machine learning on private data.

Contributions should keep the project reproducible, domain-extensible, and useful without hosted infrastructure.

## Development setup

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
pip install -e '.[dev]'
pytest -q
```

Optional molecule/RDKit work:

```bash
pip install -e '.[rdkit,dev]'
```

## Architecture

The main extension points live under `privatelabbench.core`: `Task`, `DatasetAdapter`, `ModelAdapter`, `Metric`, `Slice`, `PrivacyAudit`, and `ArtifactWriter`.

Task execution is registry-based. Third-party packages can use the `privatelabbench.tasks` Python entry-point group.

The preferred low-friction interface is a local prediction table; contributors should avoid forcing model-framework dependencies into core.

## Good first contributions

- new evaluation metrics;
- calibration/uncertainty metrics;
- slice and subgroup diagnostics;
- privacy-audit methods;
- small task/demo packs;
- report/manifest improvements;
- clearer validation errors;
- tests and documentation.

## Adding a task plugin

For an external package, expose a `TaskSpec` through:

```toml
[project.entry-points."privatelabbench.tasks"]
my-task = "my_package.plugin:task_spec"
```

Keep domain-specific dependencies in the plugin package when possible.

## Code style

- keep modules small and explicit;
- add tests for new behavior;
- prefer local-first behavior;
- avoid network calls in evaluation code;
- keep heavyweight scientific dependencies optional;
- do not introduce service/account/workspace assumptions into core.

## Privacy principle

Private scientific samples should not leave the local environment as a side effect of evaluation. Privacy claims must be precise; do not describe heuristic perturbation or attack auditing as a formal privacy guarantee.

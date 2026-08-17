# Community Benchmark Packs

Benchmark packs are small, versioned examples that package a prediction-table evaluation protocol without turning PrivateLabBench into a dataset hosting project.

The pack schema is **`benchmark-pack/v1`**.

## Pack layout

Each pack is self-contained:

```text
benchmark_packs/<pack>/
├── pack.yaml
├── config.yaml
├── predictions.csv
├── expected_receipt.json
└── README.md
```

`pack.yaml` declares:

- stable pack ID and version;
- registered PrivateLabBench task;
- scientific domain;
- description;
- data license;
- provenance type/notes;
- paths to the runnable config, prediction table, and known-good receipt.

The loader validates that pack metadata agrees with the config's `benchmark.id`, `benchmark.version`, `benchmark.domain`, and task.

## Included v1 packs

### Molecules regression

```text
community-molecules-regression@1.0.0
```

A synthetic molecular-property prediction table with SMILES metadata and series-level slices.

### Generic tabular regression

```text
community-tabular-regression@1.0.0
```

A domain-neutral regression table with site/batch metadata and slice metrics.

### Protein binary classification

```text
community-proteins-binary@1.0.0
```

A synthetic protein-sequence classification table with family metadata. Sequences, labels, and predictions are deliberately fabricated for software/evaluation testing and are not derived from a biological database.

## Use packs

List installed/source packs:

```bash
plb list-packs
```

Run by ID when there is one version:

```bash
plb run-pack community-proteins-binary
```

Or use the explicit stable ref:

```bash
plb run-pack community-proteins-binary@1.0.0
```

A pack run uses the same task registry, prediction-table protocol, reports, manifests, privacy semantics, and evaluation receipts as any other PrivateLabBench run.

## Known-good receipts

Every pack checks in a valid `evaluation-receipt/v1` fixture. It fixes the benchmark identity, input schema, sample count, task type, and expected released metrics.

Tests compare generated receipts against those semantic fields while allowing run IDs, timestamps, attestation IDs, and artifact hashes to vary.

This makes the fixtures useful for regression testing without pretending two independent runs should have identical provenance identities.

## From public benchmark to private-local evaluation

A public benchmark can be adapted without copying the full dataset into PrivateLabBench:

1. Keep dataset acquisition/preprocessing in the original benchmark ecosystem or a documented fetch script.
2. Run the model there and export stable sample IDs, targets, predictions/probabilities, and useful grouping metadata.
3. Define a PrivateLabBench pack whose `predictions.csv` is either a small license-compatible demo subset or synthetic example.
4. Use the pack config to specify benchmark identity, class order, slice fields, and release behavior.
5. Keep private evaluation data outside the repository; reuse the same config/schema against the private local prediction table.

The pack defines the **evaluation protocol**, not ownership of the underlying scientific dataset.

## Proposing a pack

Community pack PRs should:

- use `benchmark-pack/v1`;
- have a stable lowercase ID and semantic version;
- use an existing registered task unless a separate task-plugin PR is justified;
- declare license and provenance explicitly;
- avoid redistributing data without a compatible license;
- prefer synthetic or very small public examples for repository fixtures;
- include baseline predictions so users do not need model training/downloads;
- include meaningful metadata/slices when relevant;
- include a known-good shareable receipt;
- add tests that validate and run the pack.

Do not add large datasets, model weights, credentials, or private/restricted samples to benchmark packs.

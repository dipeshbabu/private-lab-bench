# PrivateLabBench Adapters

Adapters connect domain-specific data or models to the common local evaluation workflow.

The simplest integration remains a local prediction table. Model adapters are useful when a reproducible built-in baseline or direct local model integration adds value.

## Extension model

The generic `ModelAdapter` protocol no longer assumes a molecule dataset. Core extension interfaces live under `privatelabbench.core`.

Domain packages should depend on these interfaces rather than adding special cases to the central runner.

## Built-in molecule adapters

### Hashed Random Forest

```yaml
model:
  adapter: hashed_random_forest
  fingerprint: hashed
  n_bits: 256
  n_estimators: 200
```

### RDKit Morgan Random Forest

```yaml
model:
  adapter: rdkit_random_forest
  fingerprint: rdkit_morgan
  n_bits: 2048
  radius: 2
  n_estimators: 200
```

Install with `pip install -e '.[rdkit]'`.

## External predictions

```bash
plb eval-predictions predictions.csv --target target --prediction-column prediction
```

## Third-party tasks

Packages can register tasks through the Python entry-point group `privatelabbench.tasks`.

Useful contributions include scientific foundation-model adapters, proteins, materials, microscopy, robotics/trajectory evaluation, and better molecular featurizers. Heavy dependencies should remain optional.

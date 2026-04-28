# PrivateLabBench adapters

PrivateLabBench now has an adapter layer so the product can move beyond a single demo baseline and support customer-owned scientific models.

## Why this matters

The commercial workflow is not "upload your private lab data to us." The workflow is:

1. A lab runs a local adapter against its own model or prediction CSV.
2. PrivateLabBench computes metrics, shift summaries, error slices, audit metadata, and optional DP-noised reported metrics.
3. The customer can share only the report artifact with collaborators, vendors, or regulators.

## Built-in adapters

### Hashed Random Forest

No chemistry dependency required. This remains the default smoke-test adapter.

```yaml
model:
  adapter: hashed_random_forest
  fingerprint: hashed
  n_bits: 256
  n_estimators: 200
```

### RDKit Morgan Random Forest

For chemistry teams that already have RDKit installed.

```yaml
model:
  adapter: rdkit_random_forest
  fingerprint: rdkit_morgan
  n_bits: 2048
  radius: 2
  n_estimators: 200
```

Install optional dependency:

```bash
pip install -e '.[rdkit]'
```

Then run:

```bash
privatelabbench run configs/molecule_eval_rdkit.yaml
```

### External predictions

Use this when a customer already has a model and only wants private local evaluation.

```bash
privatelabbench eval-predictions examples/predictions_demo.csv \
  --target label \
  --prediction-column pred \
  --privacy dp \
  --epsilon 8
```

## Model comparison

Run multiple configs and generate one comparison report:

```bash
privatelabbench compare configs/molecule_eval.yaml configs/prediction_eval.yaml \
  --report reports/model_comparison.md \
  --json-report reports/model_comparison.json
```

## Next adapter targets

The next high-value customer adapters are:

- Molecular foundation model embeddings: ChemBERTa, MolFormer, Uni-Mol, MoLFormer-style embeddings.
- Protein and antibody models: ESM-style protein embeddings and sequence-to-property predictors.
- Robotics/VLA evaluation: trajectory-level prediction CSVs, failure probability traces, and intervention metrics.
- Scientific vision models: microscopy or materials image predictions evaluated through local prediction CSVs first, then image-folder adapters later.

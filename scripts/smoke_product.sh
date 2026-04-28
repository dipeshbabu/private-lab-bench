#!/usr/bin/env bash
set -euo pipefail

python -m pip install -e .

privatelabbench run configs/prediction_eval.yaml
privatelabbench run configs/molecule_eval.yaml
privatelabbench compare configs/prediction_eval.yaml configs/molecule_eval.yaml \
  --report reports/product_model_comparison.md \
  --json-report reports/product_model_comparison.json

privatelabbench verify-report reports/kinase_prediction_eval.json

echo "PrivateLabBench product smoke test completed."

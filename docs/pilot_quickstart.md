# Customer Pilot Quickstart

This quickstart is for a customer who wants to verify a scientific AI model claim locally and sync only sanitized evaluation evidence to a hosted PrivateLabBench dashboard.

## 1. Prepare A Prediction CSV

For regression:

```csv
label,prediction
0.12,0.10
0.35,0.39
0.74,0.70
```

For classification:

```csv
label,prediction
0,0.12
1,0.87
1,0.78
```

The `prediction` column can come from any customer model, notebook, pipeline, or internal endpoint. Raw rows stay on the customer's machine.

For a model-claim evidence report, include an optional baseline column:

```csv
label,prediction,baseline_prediction
0.12,0.10,0.20
0.35,0.39,0.45
0.74,0.70,0.62
```

## 2. Copy The Config Template

```bash
cp configs/customer_prediction_eval.template.yaml configs/customer_prediction_eval.yaml
```

Edit these fields:

```yaml
project: customer-private-prediction-eval

input:
  path: /path/to/customer_predictions.csv
  target_column: label
  prediction_column: prediction
  baseline_prediction_column: baseline_prediction
  task_type: regression

claim:
  text: Candidate model improves RMSE versus the internal baseline
  decision_metric: rmse
  direction: lower_is_better
  minimum_lift: 0.10
```

Use `task_type: classification` for binary labels.

## 3. Run Locally

Validate the edited config before running an evaluation:

```bash
privatelabbench validate-config configs/customer_prediction_eval.yaml
```

Python:

```bash
pip install -e '.[api]'
privatelabbench run configs/customer_prediction_eval.yaml
privatelabbench verify-report reports/customer_prediction_eval.json
```

Generate a model-claim evidence package:

```bash
privatelabbench evidence configs/customer_prediction_eval.yaml
```

Docker:

```bash
mkdir -p reports
chmod 777 reports

docker run --rm \
  -v "$PWD/configs:/app/configs" \
  -v "$PWD/reports:/app/reports" \
  -v "$PWD/customer_data:/data" \
  ghcr.io/dipeshbabu/private-lab-bench:0.10.0 \
  run configs/customer_prediction_eval.yaml
```

For Docker, set `input.path` in the config to the mounted path, for example `/data/customer_predictions.csv`.

## 4. Sync Sanitized Evidence To The Dashboard

```bash
privatelabbench sync-dashboard configs/customer_prediction_eval.yaml \
  --endpoint https://dashboard.example.com \
  --api-key replace-with-customer-secret \
  --organization-id customer-lab
```

Sync model-claim evidence:

```bash
privatelabbench sync-evidence configs/customer_prediction_eval.yaml \
  --endpoint https://dashboard.example.com \
  --api-key replace-with-customer-secret \
  --organization-id customer-lab
```

Browser dashboard:

```text
https://dashboard.example.com/?api_key=replace-with-customer-secret
```

Click a run ID to inspect sanitized metrics, privacy metadata, artifact hashes, and audit events.
Open `/evidence` to inspect sanitized claim recommendations and verification status.

## 5. What Stays Local

These do not need to leave the customer environment:

- raw CSV rows
- target and prediction columns
- local dataset paths
- full Markdown and JSON reports
- audit JSONL files
- model code and model outputs

The dashboard receives only sanitized evidence metadata:

- project and workflow
- task type
- sample count
- reported metrics
- privacy metadata
- artifact names and SHA256 hashes
- sanitized scalar metadata

## Troubleshooting

`401 Invalid or missing dashboard API key`

Use the API key provided for the hosted dashboard:

```bash
--api-key replace-with-customer-secret
```

`Column not found`

Check `target_column` and `prediction_column` against the CSV header.

Run the preflight command for a faster diagnosis:

```bash
privatelabbench validate-config configs/customer_prediction_eval.yaml
```

`Permission denied: reports/...` in Docker

Make the host report directory writable before mounting:

```bash
mkdir -p reports
chmod 777 reports
```

Metrics look wrong

Confirm `task_type` is correct:

- `regression` for continuous values
- `classification` for binary labels

Dashboard is empty

Run `sync-dashboard` or `sync-evidence`, then refresh the dashboard page.

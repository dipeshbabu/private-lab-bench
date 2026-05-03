# PrivateLabBench Customer Onboarding Guide

PrivateLabBench is designed for scientific teams that need to evaluate AI models on private lab data without uploading raw samples to a third-party service.

## What the customer gets

- A local CLI runner
- YAML-based repeatable evaluation configs
- Markdown reports for humans
- JSON reports for dashboards and audit trails
- JSON report integrity hashes
- Optional signed reports
- Local audit logs for config-driven evaluations
- DP-style reported metrics
- Support for customer-owned model predictions
- Multi-lab evaluation simulation through per-client CSV files

## Recommended pilot workflow

### 1. Pick one narrow evaluation task

Good first pilot tasks:

- molecular property prediction
- assay activity prediction
- protein binding score prediction
- reaction yield prediction
- materials property prediction

Start with one private CSV and one model output column.

### 2. Prepare a local CSV

For external prediction evaluation:

```csv
smiles,label,pred
CCO,0.12,0.14
CCN,0.20,0.23
c1ccccc1,0.74,0.71
```

The customer can generate `pred` using any private model, notebook, internal pipeline, or model endpoint.

### 3. Create a config

```yaml
project: customer-assay-eval
workflow: predictions

input:
  path: /data/customer_predictions.csv
  target_column: label
  prediction_column: pred
  task_type: regression

privacy:
  mode: dp
  epsilon: 8
  sensitivity: 1
  seed: 13

report:
  markdown: /data/reports/customer_assay_eval.md
  json: /data/reports/customer_assay_eval.json

audit:
  path: /data/reports/customer_assay_audit.jsonl
```

### 4. Run locally with Python

```bash
pip install -e .
privatelabbench run configs/prediction_eval.yaml
privatelabbench verify-report reports/kinase_prediction_eval.json
```

### 5. Run locally with Docker

Build the image:

```bash
docker build -t privatelabbench:local .
```

Run the included demo config:

```bash
mkdir -p reports
chmod 777 reports

docker run --rm \
  -v "$PWD/reports:/app/reports" \
  privatelabbench:local run configs/prediction_eval.yaml
```

Run against customer-owned local data:

```bash
mkdir -p reports
chmod 777 reports

docker run --rm \
  -v "$PWD/customer_data:/data" \
  -v "$PWD/reports:/app/reports" \
  privatelabbench:local run /data/customer_eval.yaml
```

### 6. Verify and share artifacts

The customer can share only these outputs with the vendor or internal stakeholders:

- Markdown report
- JSON report
- audit JSONL file
- verification output from `privatelabbench verify-report`

Raw dataset rows do not need to leave the customer environment.

## Privacy model for the MVP

PrivateLabBench currently provides a local-first evaluation workflow. Raw data stays in the customer's environment when the runner is executed locally or inside the customer's Docker environment.

The current MVP supports DP-style metric perturbation for reported metrics. This should be described as a product prototype rather than a formal compliance guarantee.

## Pilot success criteria

A pilot is successful if the customer can answer:

- Does our model work on private held-out scientific data?
- Which metric moved under private reporting?
- Is there visible dataset shift across labs or batches?
- Can the evaluation be repeated from a config file?
- Can our team share only the report, not the raw data?
- Can our team verify the report has not been changed after generation?

## Suggested 4-week paid pilot

### Week 1: Setup

- Confirm task and data format
- Create customer config
- Run first local prediction evaluation
- Produce Markdown and JSON reports
- Verify JSON report integrity

### Week 2: Benchmarking

- Evaluate 2-3 model variants
- Compare reported metrics
- Identify dataset shift or error slices

### Week 3: Multi-site or multi-batch evaluation

- Split by lab, assay batch, partner, or time period
- Run federated-style local aggregation
- Produce aggregate report

### Week 4: Decision package

- Final benchmark report
- Privacy/utility summary
- Report verification summary
- Deployment recommendation
- Next-step integration plan

## What not to claim yet

Until implemented and audited, do not claim:

- HIPAA compliance
- SOC 2 compliance
- cryptographic secure aggregation
- production-grade federated learning
- clinical or regulated diagnostic use

## Best first customer profile

The best first customer is an AI-first biotech or scientific ML team with proprietary assay data and one or more internal models they want to benchmark privately.

# PrivateLabBench Federated Evaluation Report

## Run summary
- Client directory: `examples/labs`
- Target column: `label`
- Clients: 3
- Total samples: 60
- Task type(s): regression
- Model(s): RandomForestRegressor

## Privacy mode
DP-style metric noise applied with epsilon=8, sensitivity=1.

## Aggregate clean metrics
- mae: 0.178000
- rmse: 0.214000
- r2: -0.090000

## Aggregate privacy-preserving reported metrics
- mae: 0.135000
- rmse: 0.270000
- r2: -0.130000

## Aggregate dataset shift summary
- mean_feature_l2_shift: 0.520000
- train_density: 0.024000
- test_density: 0.024000

## Per-client results

### lab_a
- Source: `examples/labs/lab_a.csv`
- Samples: 20
- Train/Test split: 15 / 5
- Task type: regression
- Model: RandomForestRegressor

Clean metrics:
- mae: 0.180000
- rmse: 0.220000
- r2: -0.080000

Reported metrics:
- mae: 0.140000
- rmse: 0.280000
- r2: -0.120000

### lab_b
- Source: `examples/labs/lab_b.csv`
- Samples: 20
- Train/Test split: 15 / 5
- Task type: regression
- Model: RandomForestRegressor

### lab_c
- Source: `examples/labs/lab_c.csv`
- Samples: 20
- Train/Test split: 15 / 5
- Task type: regression
- Model: RandomForestRegressor

## Notes
This report simulates a multi-lab private evaluation workflow. Each client CSV is evaluated independently, then only aggregate metrics and summaries are combined. Raw scientific samples are not uploaded by this CLI.

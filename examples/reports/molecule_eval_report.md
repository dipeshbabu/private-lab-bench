# PrivateLabBench Evaluation Report

## Dataset
- Source: `examples/molecules_demo.csv`
- Target column: `label`
- Samples: 20
- Train/Test split: 15 / 5

## Model
- Baseline: RandomForestRegressor
- Task type: regression

## Clean local metrics
- mae: 0.185200
- rmse: 0.220813
- r2: -0.076418

## Privacy-preserving reported metrics
- mae: 0.116485
- rmse: 0.327222
- r2: -0.169835

## Privacy mode
DP-style metric noise applied with epsilon=8, sensitivity=1.

## Dataset shift summary
- mean_feature_l2_shift: 0.531972
- train_density: 0.023958
- test_density: 0.024219

## Notes
PrivateLabBench v0.1 runs evaluation locally and reports only metrics. Raw scientific samples are not uploaded by this CLI.

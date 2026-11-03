# Controlled Caco2 model-selection result

Original official public Caco2 holdout plus a synthetic +0.8 target-scale offset for MolLogP>=3.0; same compounds/IDs, not new private lab data or independent cohorts.

| Evaluation | MAE | Quality |
| --- | ---: | --- |
| Original held-out candidate | 0.433154 | pass |
| Synthetic proxy candidate | 0.604110 | fail |
| Synthetic proxy training mean | 0.734978 | fail |

Paired improvement of candidate over baseline: 0.130868. Model A is the forest reference; Model B is the training-mean reference. Practical threshold: 0.02.

Paired interval: {'confidence_level': 0.95, 'estimate': 0.13086801530360537, 'lower': 0.07186514363831507, 'method': 'paired_cluster_percentile_bootstrap', 'metric_basis': 'clean_metrics', 'n_independent_units': 140, 'n_samples': 182, 'resamples': 1000, 'sampling': 'independent_clusters', 'seed': 13, 'status': 'evaluated', 'upper': 0.19147195654220703, 'valid_resamples': 1000}

Reference/current changes reuse public compounds and IDs; independent-cohort delta intervals are withheld. Connectivity clusters are an inferential assumption, not proof of chemical independence.

The signed files authenticate a pinned example issuer's statement. Execution and scientific validity are not independently verified. Raw rows, model parameters, keys, full audit evidence, and paths remain under local/.

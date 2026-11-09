# Controlled Caco2 model-selection result

Original official public Caco2 holdout plus a synthetic +0.8 target-scale offset for MolLogP>=3.0; same compounds/IDs, not new private lab data or independent cohorts. Cohort: synthetic_measurement_shift_proxy

| Evaluation | MAE | Quality |
| --- | ---: | --- |
| Original held-out candidate | 0.433154 | pass |
| Synthetic proxy candidate | 0.604110 | fail |
| Synthetic proxy training mean | 0.734978 | fail |

Overall proxy MAE: 0.604110 exceeds the predeclared limit 0.600000 (182 observations; 140 connectivity units): fail.

Overall proxy MAE interval upper bound: 0.663107 meets the predeclared limit 0.700000: pass.

Critical high-logP group MAE: 0.849552 exceeds the predeclared limit 0.700000 (61 observations; 59 connectivity units): fail.

Paired improvement of candidate over baseline: 0.130868. Model A is the forest reference; Model B is the training-mean reference. Predeclared practical improvement threshold: 0.020000.

Paired interval: [0.071865, 0.191472]; its lower bound meets the predeclared practical improvement criterion (at least 0.020000).

Relative improvement does not waive an overall or critical-group quality failure. Limits come from the public frozen case protocol; model-quality and aggregate-release decisions are separate.

Reference/current changes reuse public compounds and IDs; independent-cohort delta intervals are withheld. Connectivity clusters are an inferential assumption, not proof of chemical independence.

The signed files authenticate a pinned example issuer's statement. Execution and scientific validity are not independently verified. Raw rows, model parameters, keys, full audit evidence, and paths remain under local/.

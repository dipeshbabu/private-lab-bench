# Sampling units and slice inference

Repeated observations from one patient, compound, assay, or laboratory can remain dependent. Declare the independent sampling unit before interpreting an interval:

```bash
plb evaluate predictions.csv --task-type regression \
  --sampling-design examples/sampling_design.yaml
plb compare candidate.csv baseline.csv --task-type regression \
  --sampling-design examples/sampling_design.yaml --slice-columns site
```

The example requires a `patient_id` column in your own prediction tables. Ordinary row/target-stratified behavior remains available when no sampling design is declared. A protocol with a fixed row design rejects a conflicting cluster override: put the design in a new protocol version instead.

## Whole independent clusters

```yaml
schema_version: sampling-design/v1
unit: patient
method: cluster_bootstrap
cluster_columns: [patient_id]
sampling_level: patient_id
min_independent_units: 20
strata_column: null
resample_rows_within_leaf: false
max_resample_rows: 2000000
exchangeability: model_vectors_within_clusters
```

Each bootstrap draw samples the original number of independent clusters with replacement and retains **every observation** in each selected cluster. Paired comparisons apply the same draw to both models. Unequal cluster sizes are retained: the point estimand remains the observation-weighted metric, and a resampled dataset can contain a different number of rows. This does not turn the result into an equal-weight mean of per-patient or per-site metrics.

`strata_column` optionally preserves the observed cluster count in each declared stratum. A stratum must be constant within its top-level cluster and contain at least two clusters. This is cluster-level stratification; the tool does not split mixed-label clusters to preserve row class counts.

Local results record observations, independent-unit count, cluster-size range/median, method, seed, resamples, reliability flags, and assumptions. The default minimum of 20 independent units is an operational safeguard, not a universal coverage guarantee. Changing it is an explicit scientific choice. Many repeated rows do not replace missing independent units. One-class/degenerate resamples remain undefined; insufficient valid draws do not produce an interval.

Regression cluster draws use bounded batches of exact cluster sums to compute MAE, RMSE, and R² without materializing repeated member rows. Paired models share those draws. A resample exceeding the declared row budget invalidates the interval rather than silently dropping large draws and conditioning the result on resource use.

## Nested designs

For nested laboratories and patients:

```yaml
schema_version: sampling-design/v1
unit: laboratory
method: hierarchical_bootstrap
cluster_columns: [site_id, patient_id]
sampling_level: site_id
min_independent_units: 20
resample_rows_within_leaf: false
exchangeability: none
```

Columns run from the top independent unit to the leaf unit. The sampler draws top-level units and then child units within each selected parent, retaining leaf observations. Set `resample_rows_within_leaf: true` only when exchangeable leaf observations match the sampling experiment you intend to represent. Hierarchies support up to eight declared levels. Child IDs must identify one parent globally; crossed arrangements return `not_supported_crossed_clusters`. Do not rename genuine shared units to make a crossed design appear nested.

The design must match the scientific question and sampling process. [Saravanan, Berman, and Sober](https://sober-lab.org/wp-content/uploads/2020/07/Saravanan-et-al-2020.pdf) discuss hierarchical resampling, unequal representation, and the limits of small upper-level samples. The implementation here uses the declared observation-weighted estimand; it does not inherit every analysis choice from that paper.

Missing group IDs, unsupported nesting/strata, too few independent units, insufficient valid draws, and resource limits produce explicit unavailable statuses. There is no automatic fallback to row resampling. Reference/current diagnostics use the same declared design and withhold independent-cohort delta intervals when either sample IDs or top-level units overlap.

## Prediction-swap tests

Whole-cluster prediction swaps require `exchangeability: model_vectors_within_clusters`. Under that declared null, a swap exchanges both models' complete prediction vectors for an independent cluster. Individual member rows are not swapped independently. The two-sided Monte Carlo p-value includes the usual plus-one correction.

Without the exchangeability declaration, the test says `exchangeability_not_declared`. Hierarchical prediction-swap tests are currently `not_supported_nested_permutation`; hierarchical bootstrap intervals remain available. A bootstrap interval is not a substitute for an exchangeability assumption or a valid hypothesis-test p-value.

## Declared slice families

Add an optional policy to a sampling design for paired slice tests:

```yaml
critical_slices:
  - {column: site, value: external}
multiplicity:
  schema_version: multiplicity/v1
  method: benjamini_yekutieli
  family: exploratory_slices
  alpha: 0.05
  dependence: arbitrary
```

Critical selectors are marked `prespecified_critical`; other requested slices are exploratory. Choose `family: critical_slices` to adjust only the declared critical family. Fix the family and selectors before inspecting outcomes. Missing/underpowered/undefined tests stay in that family as conservative non-rejections, with null adjusted values and explicit counts. Disabled permutations do not produce corrected claims. A single-table evaluation has no model-comparison hypothesis tests and reports correction as not applied.

Benjamini–Yekutieli is the default for valid p-values with arbitrary dependence. Benjamini–Hochberg requires an explicit `dependence: independent_or_prds` declaration; selecting it does not establish that assumption. See the [SciPy reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html) and the [original dependency analysis](https://www.math.tau.ac.il/~ybenja/depApr27.pdf). Adjusted p-values do not adjust confidence intervals, establish causality, or replace practical effect thresholds. Exploratory interval scans remain unadjusted.

## Receipts and disclosure

Group IDs and full design settings stay local. A protocol's optional `sampling_design` participates in its canonical digest; inferential-design changes require a new protocol version. Existing row-protocol identities remain unchanged.

Release minimums apply to declared independent-unit counts as well as row counts. A small independent-unit cell withholds the complete slice partition. Public methods/counts omit private grouping keys and selectors. Additional slice intervals/tests and correction results require explicit policy flags:

```yaml
include_slice_inference: true
include_multiplicity: true
slices:
  site: [internal, external]
```

These fields supplement a complete reviewed release policy. Correction output requires its complete family to lie within the approved partition and satisfy the unit/cell thresholds; partial or unapproved families are withheld. The writer recomputes adjusted p-values from approved test evidence. Disclosure approval authenticates none of the scientific assumptions, dataset truth, model execution, or training independence.

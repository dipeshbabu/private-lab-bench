---
icon: material/clipboard-check-outline
---

# Split integrity and training-reference audits

Use an `evaluation-design/v1` declaration to check supported leakage conditions before interpreting a score:

```bash
plb audit-design --evaluation evaluation.csv \
  --training-reference original_training_ids.csv --reference-complete \
  --protocol design.yaml --out reports/design_audit.json
```

This command writes a **local-only** audit artifact and prints statuses/counts without row identifiers. A protocol can be a standalone design YAML or an exact evaluation protocol containing `evaluation_design`. The audit records its algorithm, rule digest, input snapshots, reference declarations, optional adapter version, and scoped findings.

An unavailable, empty, or incomplete original training reference returns `not_testable`. A negative audit applies to supplied records and declared rules; it cannot exclude undisclosed pretraining, unknown identifier aliases, or an inaccurate completeness declaration. There is no `no_leakage` certificate.

## Declare the actual study design

Start from `examples/evaluation_design.yaml`, adjusting its required `qc_pass` column and rules to your data. Default partition aliases are `train`, `validation`, and `test`. Custom aliases must be declared explicitly. A configured evaluation split column is required; set `split_column: null` only when the file is explicitly one evaluation partition. A reference file without split metadata is declared to contain the training-reference partition. Mixed files require correct split metadata.

The auditor checks exact repeated IDs and overlap across forbidden partition pairs. Optional `entity_columns` define a composite scientific identity, and `group_columns` check each prohibited shared grouping key independently. Different row IDs do not make repeated compounds, patients, or assay groups independent.

```yaml
entity_columns: [entity_id, assay_id]
group_columns: [subject_id]
label_column: target
repeated_entities: allow
conflicting_labels: warn
label_tolerance: 0.0
```

Choose identity keys and a justified numeric tolerance for your scientific setting. Legitimate repeated measurements can be allowed; different assay conditions may need to participate in the composite identity. A conflicting-label check is unavailable when required labels are missing. Repeated training records mirrored across two reference sources are not treated as new within-set measurements.

Optional chronology rules use ISO dates/timestamps normalized to declared UTC:

```yaml
chronology:
  column: collected_at
  cutoff: "2025-01-01"
  strictly_before: true
  timezone: UTC
```

Training/reference and prior validation records must precede the scored evaluation records; the cutoff additionally places training before the boundary and evaluation on or after it. `strictly_before: false` permits ties. Missing or unsupported date evidence remains untestable. This checks supplied timestamps; it does not independently establish when a model obtained information.

## Eligibility is applied before scoring

Predeclare generic QC/eligibility exclusions with `equals`, `less_than`, `greater_than`, or `is_missing`. Comparisons accept scalar values, not executable expressions or lists of individual identifiers. Rules apply only to the scored evaluation partition. All training/reference records remain available for overlap checks, so excluding a QC-failed evaluation row cannot erase a training witness.

```bash
plb evaluate predictions.csv --evaluation-design design.yaml \
  --training-reference original_training_ids.csv --reference-complete
```

The runner audits a local snapshot, selects the declared partition/eligible rows, and passes that exact in-memory table to scoring and baseline evaluation. No intermediate CSV of private rows is written. Reference/current diagnostics apply the same rules to both cohorts and retain both audits. Missing targets/predictions after declared exclusions are rejected rather than silently dropped.

Known violations stop scoring by default and leave the local audit JSON. `--design-failure-mode local_only` permits debugging valid prediction tables, retains a failing exit status, and still blocks publication. An unavailable original training reference can accompany a conditional performance score, but remains explicitly `not_testable`.

For paired prediction comparison, the same design selects both tables before exact-ID alignment. `--training-reference` is a common reference declaration for both models; use it only when those records actually apply to both. Each model retains its own audit and input snapshot. A fixed protocol binds the complete design in its digest; conflicting overrides require a new protocol version.

The evaluation unit in a split audit does not automatically define an uncertainty sampler. Use a [sampling design](sampling_design.md) for correlated or nested observations.

## Optional molecular checks

Install the optional adapter with `pip install -e '.[rdkit]'`, then select it explicitly:

```yaml
adapter:
  name: rdkit-molecule/v1
  smiles_column: smiles
  canonical_isomeric: true
  identity_overlap: forbid
  scaffold_overlap: forbid
  scaffold_include_chirality: false
  near_duplicates:
    threshold: 0.9
    radius: 2
    bits: 2048
    max_pairs: 100000
    policy: warn
```

Canonical SMILES check the declared molecular graph/stereochemistry; they do not standardize every salt, tautomer, or experimental entity. [RDKit Murcko scaffolds](https://rdkit.org/docs/source/rdkit.Chem.Scaffolds.MurckoScaffold.html) support explicitly declared scaffold-disjoint rules. Empty acyclic scaffolds are not treated as one shared contaminating scaffold; an unavailable scaffold comparison is untestable. Related scaffolds do not automatically imply leakage, so scaffold overlap is allowed unless a stricter rule is declared.

The optional Morgan/Tanimoto comparison is a labeled heuristic with declared parameters. If its complete comparison family exceeds the pair budget, the check is untestable; partial comparisons do not produce a negative finding. Invalid molecules fail, unavailable optional dependencies remain explicit, and runtime RDKit versions are recorded. Official benchmark splits remain the benchmark's responsibility; the auditor does not invent replacement splits.

## Quality and release decisions

A `quality-policy/v1` can require scoped design evidence:

```yaml
schema_version: quality-policy/v1
design:
  require_pass: true
  max_overlap_records: 0
  max_duplicate_records: 0
  max_conflicting_labels: 0
```

```bash
plb gate reports/design_audit.json --policy quality.yaml
```

Thresholds use the maximum affected-record count across the corresponding declared checks. Missing, unrequested, incomplete, or suppressed evidence returns `investigate`; a known exceeded threshold fails. Exit codes remain 0/1/2 for pass/fail/investigate.

Local receipts retain private paths, input hashes, rule definitions, and bounded identifier examples. Public audit summaries require `include_design_audit: true` in a reviewed release policy. `require_design_audit: true` additionally demands a passing, present, completeness-declared reference audit for every evaluated model/cohort. Small audit cells withhold the summary; raw IDs, molecular fingerprints, source-file hashes, and examples are never exported. Failed audits block release even when the policy omits the strict requirement.

Scientific split auditing is separate from privacy auditing, signer authentication, trusted execution, and prospective/clinical/regulatory validation. An artifact can verify a declared result without independently establishing those facts.

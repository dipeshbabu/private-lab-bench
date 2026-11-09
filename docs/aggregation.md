---
icon: material/lan
---

# Aggregate results across sites

Declared independent-unit counts stay attached to each site's point estimate and
interval, including paired comparisons. Before publication, each declared count
must meet the destination policy's larger `min_samples`/`min_cell_size` floor.
A weaker source approval does not waive this new review. Clustered statistics
with missing counts, contradictory counts, or counts that exceed the observations
are rejected. Paired evidence must match the corresponding model/site population.
Legacy IID receipts without independent-unit metadata remain readable.

Rebuild older local aggregates from their original receipts before exporting:
older scalar aggregates could discard this sampling metadata. The counts remain
evaluator declarations; these checks do not independently verify participant IDs.

`plb aggregate` consumes verified **shareable** artifacts. It does not load raw tables, targets, or predictions. Every input must declare the same exact protocol ID, version, digest, metrics, task, input schema, benchmark identity, and metric basis. Local receipts, duplicate receipts, missing model/site combinations, and incompatible definitions are rejected.

First run each local dataset under an approved versioned protocol. Its release policy must explicitly approve `include_protocol: true`. Exchange only the resulting `.shareable.json` receipts.

```bash
plb aggregate lab-a.shareable.json lab-b.shareable.json \
  --site lab-a --site lab-b --model published-model@frozen-1 \
  --metric rmse --out reports/cross_site.json
plb verify reports/cross_site.json
```

If labels are omitted, inputs receive anonymous `site-1`, `site-2`, etc. in input order. Filenames never become site identities. `--model` is an explicit declaration of the evaluated model and revision; it does not prove which model produced predictions. Authenticated Ed25519 receipts with a model-bound signer statement can supply that identity instead. Use `--trust-store trusted-keys.yaml --require-trusted-signer` to require every input to authenticate against pinned, unrevoked keys. Self-contained hashes alone establish consistency.

## Read site results first

The terminal and artifact show each site's N, estimate, available interval, and descriptive best-to-worst range before any pooled result. `--range-threshold 0.1` marks a gap above your predeclared practical threshold. Worst-site labels reflect the metric's direction. No universal outlier threshold, heterogeneity significance test, or causal explanation is inferred from a handful of scores. A site with the worst point estimate may still have substantial uncertainty.

Site intervals retain their source method and confidence level. They are never combined into a purported pooled confidence interval. Clustered observations still need an appropriate upstream sampling design; aggregation cannot repair an unsuitable row bootstrap.

## When pooling is valid

By default, pooling is withheld because receipts cannot establish whether sites contain overlapping observations. `--assume-disjoint-sites` explicitly declares disjoint observations and identical scoring, normalization, and observation-weighting semantics. Under those assumptions, the following point identities hold, with site counts `n_i` and total `N`:

| Metric | Pooled point estimate |
| --- | --- |
| MAE | `sum(n_i * MAE_i) / N` |
| Accuracy | `sum(n_i * accuracy_i) / N` |
| Log loss | `sum(n_i * log_loss_i) / N`, with identical labels/clipping semantics |
| RMSE | `sqrt(sum(n_i * RMSE_i**2) / N)` |
| AUROC, R², F1 and macro/weighted variants | Not recoverable from these site scalars |

These identities follow by combining the per-observation sums underlying each supported mean. Averaging site AUROCs does not recover cross-site positive/negative rankings, and averaging R² loses the global target variance. The tool therefore keeps these metrics at site level. It does not invent a meta-analysis from missing standard errors. Perturbed metrics are also withheld from point pooling. No pooled confidence interval can be reconstructed from the receipt summaries supplied here.

## Several models and paired evidence

For scalar evaluation receipts, repeat `--model` once per input and reuse explicit `--site` labels. Every model must cover the same complete set of sites. These remain descriptive model comparisons; matching site names do not establish matching observations.

For inferential within-site candidate/baseline comparisons, produce protocol-bound paired artifacts first:

```bash
plb compare candidate.csv baseline.csv --target target \
  --protocol plb://generic/regression@1.0.0 \
  --release-policy paired-release.yaml --json-report reports/lab_a_pair.json
plb aggregate reports/lab_a_pair.shareable.json reports/lab_b_pair.shareable.json \
  --site lab-a --site lab-b --model candidate@1 --model baseline@1 \
  --out reports/paired_sites.json
```

Supply the first and second models in the same order as every paired artifact. Each source must use the same protocol's frozen comparison settings. The aggregate preserves the direction-adjusted improvement and paired interval for each site, with two aligned model tables. It does not combine site intervals or p-values into an unsupported global paired claim. Mixing scalar receipts and paired artifacts in one aggregate is rejected.

## Reviewed aggregate export

The local aggregate contains input verification evidence. Public output is written only after a fresh release-policy check; its Markdown is rendered solely from the approved public artifact. A policy must approve every published site label and model identity, protocol identity, count thresholds, and its audit requirements. Example:

```yaml
schema_version: release-policy/v1
id: cross-site-public-review
enabled: true
min_samples: 20
min_cell_size: 5
require_privacy_audit: false  # Receipt-only operation; no new row-level audit is claimed.
include_protocol: true
public_sites: [lab-a, lab-b]
public_models:
  - {id: published-model, revision: frozen-1}
```

Pass this with `--release-policy aggregate-release.yaml`. The public writer recomputes summaries from approved scalar fields, discards paths, source hashes, arbitrary plugin metadata, and input verification details, and enforces the release ledger for changed repeated exports. A failed re-run removes obsolete public JSON and Markdown. A new aggregate hash authenticates none of its underlying scientific claims; inspect source signer trust, protocol assumptions, dataset independence, and representativeness separately.

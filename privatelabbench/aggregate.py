"""Receipt-only site summaries; no access to targets, predictions, or raw datasets."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from privatelabbench.eval.metrics import METRIC_DIRECTIONS
from privatelabbench.reports.integrity import attach_integrity_metadata, verify_payload
from privatelabbench.reports.receipt import validate_receipt_shape
from privatelabbench.reports.trust import _identifier

AGGREGATE_SCHEMA = "cross-site-aggregate/v1"
LINEAR_METRICS = frozenset({"mae", "accuracy", "log_loss"})
LIMITATIONS = [
    "Site labels and unsigned model identities are declarations by the aggregator.",
    "Hashes establish consistency; signer authentication requires independently pinned keys.",
    "Protocol claims do not establish execution, dataset truth, or model-training independence.",
    "Site ranges are descriptive; they are not a statistical heterogeneity test or causal explanation.",
    "Pooling requires declared disjoint observations with identical scoring semantics and weighting.",
    "Receipt summaries cannot recover pooled confidence intervals or paired inference between unpaired model runs.",
]


def model_identity(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "revision"}:
        raise ValueError("Model identity requires exactly id and revision")
    return {key: _identifier(value[key]) for key in ("id", "revision")}


def _finite(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{label} must be a finite numeric estimate")
    return float(value)


def _count(value: Any) -> int:
    if type(value) is not int or value < 2:
        raise ValueError("Each site needs an explicit sample count of at least two")
    return value


def _population_units(count: int, *records: Mapping[str, Any]) -> int | None:
    """Keep declared population counts bound to their observation/inference data."""
    from privatelabbench.privacy.export import _uses_cluster_units

    units = set()
    clustered = False
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Invalid site sampling metadata")
        if "n_samples" in record and (
            type(record["n_samples"]) is not int or record["n_samples"] != count
        ):
            raise ValueError("Sampling observation count differs from the site count")
        if "n_independent_units" in record:
            value = record["n_independent_units"]
            if type(value) is not int or not 2 <= value <= count:
                raise ValueError("Invalid site independent-unit count")
            units.add(value)
        clustered |= _uses_cluster_units(record)
    if len(units) > 1 or clustered and not units:
        raise ValueError("Missing or inconsistent site independent-unit metadata")
    return next(iter(units)) if units else None


def _require_population_floor(units: int | None, policy: Mapping[str, Any]) -> None:
    if units is not None and units < max(
        policy["min_samples"], policy["min_cell_size"]
    ):
        raise ValueError("Site independent-unit count is below release thresholds")


def summarize_sites(
    sites: Sequence[Mapping[str, Any]],
    metric: str,
    *,
    disjoint: bool,
    range_threshold: float | None = None,
) -> dict[str, Any]:
    """Exact count-weighted identities only; nonlinear metrics remain site-level."""
    if metric not in METRIC_DIRECTIONS or len(sites) < 2:
        raise ValueError("At least two sites and a supported metric are required")
    if range_threshold is not None and _finite(range_threshold, "range_threshold") < 0:
        raise ValueError("range_threshold must be nonnegative")
    values = [_finite(site["estimate"], "site estimate") for site in sites]
    counts = [_count(site["n_samples"]) for site in sites]
    for site, value in zip(sites, values):
        if site.get("privacy_mode", "none") == "none" and (
            (metric in {"mae", "rmse", "log_loss"} and value < 0)
            or (
                metric not in {"mae", "rmse", "log_loss", "r2", "spearman"}
                and not 0 <= value <= 1
            )
            or (metric == "spearman" and not -1 <= value <= 1)
            or (metric == "r2" and value > 1)
        ):
            raise ValueError("Exact metric estimate is outside its mathematical range")
    lower = METRIC_DIRECTIONS[metric] == "lower_is_better"
    best = min(values) if lower else max(values)
    worst = max(values) if lower else min(values)
    spread = max(values) - min(values)
    pooled: dict[str, Any] = {
        "status": "not_poolable_from_site_metrics",
        "estimate": None,
        "confidence_interval": None,
    }
    if metric in LINEAR_METRICS or metric == "rmse":
        if not disjoint:
            pooled["status"] = "requires_disjoint_sites_declaration"
        elif any(site.get("privacy_mode", "none") != "none" for site in sites):
            pooled["status"] = "not_poolable_from_perturbed_metrics"
        else:
            total = sum(counts)
            # Normalize before multiplying to avoid overflowing large counts.
            estimate = (
                math.hypot(
                    *(math.sqrt(n / total) * value for n, value in zip(counts, values))
                )
                if metric == "rmse"
                else math.fsum(n / total * value for n, value in zip(counts, values))
            )
            if not math.isfinite(estimate):
                raise ValueError("Pooled estimate is not finite")
            pooled.update(
                status="point_estimate_only",
                estimate=estimate,
                formula=(
                    "sqrt_weighted_mean_squared_rmse"
                    if metric == "rmse"
                    else "sample_weighted_mean"
                ),
                interval_status="not_recoverable_from_site_summaries",
            )
    return {
        "total_samples": sum(counts),
        "n_sites": len(sites),
        "range": {
            "min": min(values),
            "max": max(values),
            "absolute": spread,
            "relative_to_best": spread / abs(best) if best else None,
            "best_sites": [
                site["site"] for site, value in zip(sites, values) if value == best
            ],
            "worst_sites": [
                site["site"] for site, value in zip(sites, values) if value == worst
            ],
            "practical_threshold": range_threshold,
            "material": (
                spread > range_threshold if range_threshold is not None else None
            ),
        },
        "pooled": pooled,
    }


def aggregate_receipts(
    paths: Sequence[str | Path],
    *,
    sites: Sequence[str] | None = None,
    models: Sequence[Mapping[str, str]] | None = None,
    metric: str | None = None,
    assume_disjoint_sites: bool = False,
    range_threshold: float | None = None,
    signing_secret: str | None = None,
    trust_store: Mapping[str, Any] | None = None,
    require_trusted_signer: bool = False,
    require_external_validation: bool = False,
) -> dict[str, Any]:
    if len(paths) < 2:
        raise ValueError("Supply at least two shareable receipts")
    labels = (
        list(sites)
        if sites is not None
        else [f"site-{i + 1}" for i in range(len(paths))]
    )
    if len(labels) != len(paths) or any(
        not isinstance(label, str) or not label for label in labels
    ):
        raise ValueError("Supply one nonempty --site label per input, in input order")
    if type(assume_disjoint_sites) is not bool:
        raise ValueError("assume_disjoint_sites must be boolean")
    if type(require_external_validation) is not bool:
        raise ValueError("require_external_validation must be boolean")
    parsed_models = [model_identity(value) for value in models or ()]
    seen_hashes, seen_ids = set(), set()
    compatibility = None
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    validation_digests = {}
    paired_sites, verification = [], []
    kind = None
    for index, path in enumerate(paths):
        # Read once: verification and aggregation use the same snapshot.
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("scope") != "shareable"
            or "local" in payload
        ):
            raise ValueError(
                "Aggregation accepts shareable artifacts only; export local receipts through a reviewed release policy first"
            )
        schema = payload.get("schema_version")
        if (
            schema not in {"evaluation-receipt/v1", "paired-comparison-artifact/v1"}
            or kind is not None
            and schema != kind
        ):
            raise ValueError(
                "Use one compatible artifact family: evaluation receipts or paired comparisons"
            )
        kind = schema
        if schema == "evaluation-receipt/v1":
            validate_receipt_shape(payload)
        check = verify_payload(
            payload,
            signing_secret=signing_secret,
            trust_store=trust_store,
            require_trusted_signer=require_trusted_signer,
        )
        if not check["valid"]:
            raise ValueError(
                f"Input {index + 1} failed verification: {check['reason']}"
            )
        digest = check["payload_sha256"]
        identifier = payload.get(
            "receipt_id" if schema == "evaluation-receipt/v1" else "comparison_id"
        )
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in seen_ids
            or digest in seen_hashes
        ):
            raise ValueError("Duplicated or missing receipt/comparison identity")
        seen_hashes.add(digest)
        seen_ids.add(identifier)
        shared = payload["shareable"]
        upstream = (
            shared.get("privacy", {}).get("release", {})
            if schema == "evaluation-receipt/v1"
            else shared.get("release", {})
        )
        if (
            upstream.get("decision") != "allow"
            or schema == "evaluation-receipt/v1"
            and (
                upstream.get("status") != "pass"
                or upstream.get("publishable") is not True
            )
        ):
            raise ValueError(
                "Input is missing a successful upstream release decision; re-export with a reviewed release policy"
            )
        evaluation = (
            shared["evaluation"] if schema == "evaluation-receipt/v1" else shared
        )
        from privatelabbench.privacy.export import protocol_identity

        protocol = protocol_identity(evaluation.get("protocol"))
        validation_model = None
        if require_external_validation:
            from privatelabbench.external_validation import SCHEMA, public_approval

            validation = evaluation.get("external_validation", {})
            if validation.get("schema_version") != SCHEMA:
                raise ValueError(
                    "Every input must contain an approved external-validation profile"
                )
            approved = public_approval(
                {
                    key: validation[key]
                    for key in ("model", "dataset", "evaluator_relationship")
                }
            )
            validation_model = {
                key: approved["model"][key] for key in ("id", "revision")
            }
            model_key = tuple(validation_model.values())
            model_digest = approved["model"]["artifact_sha256"]
            if (
                model_key in validation_digests
                and validation_digests[model_key] != model_digest
            ):
                raise ValueError(
                    "The same external-validation model revision has conflicting artifact digests"
                )
            validation_digests[model_key] = model_digest
        chosen_metric = metric or protocol["primary_metric"]
        if chosen_metric not in protocol["metrics"]:
            raise ValueError("Selected metric must be declared in the protocol")
        task_type = evaluation.get("task_type")
        input_schema = (
            evaluation.get("input_schema", {}).get("schema_version")
            if schema == "evaluation-receipt/v1"
            else evaluation.get("comparison_schema")
        )
        expected_schema = (
            "prediction-table/v1"
            if schema == "evaluation-receipt/v1"
            else "paired-comparison/v1"
        )
        if input_schema != expected_schema or task_type not in {
            "regression",
            "classification",
            "multiclass",
        }:
            raise ValueError("Incompatible task or input schema")
        from privatelabbench.protocols import TASK_METRICS

        if not set(protocol["metrics"]) <= TASK_METRICS[task_type]:
            raise ValueError("Protocol metrics conflict with task type")
        if (
            schema == "evaluation-receipt/v1"
            and evaluation.get("metric_source") != "reported_metrics"
        ):
            raise ValueError("Only reported prediction-table metrics are supported")
        mode = shared.get("privacy", {}).get("mechanism", {}).get("mode", "none")
        if mode not in {"none", "metric_perturbation"}:
            raise ValueError("Unsupported metric privacy basis")
        key = {
            "schema": schema,
            "protocol": protocol,
            "metric": chosen_metric,
            "task_type": task_type,
            "benchmark": shared.get("benchmark", {}),
            "privacy_mode": mode,
        }
        if compatibility is not None and key != compatibility:
            raise ValueError(
                "Incompatible protocol digest, task, metric, benchmark identity, or metric basis across inputs"
            )
        compatibility = key
        site = labels[index]
        if schema == "evaluation-receipt/v1":
            if parsed_models and len(parsed_models) not in {1, len(paths)}:
                raise ValueError("Use one --model for all receipts, or one per receipt")
            declared = (
                parsed_models[0 if len(parsed_models) == 1 else index]
                if parsed_models
                else None
            )
            claimed = payload.get("signer_statement", {}).get("model")
            if claimed is not None:
                claimed = model_identity(claimed)
            if declared is not None and claimed is not None and declared != claimed:
                raise ValueError(
                    "Declared model conflicts with the receipt signer statement"
                )
            if declared is None and (
                claimed is None or not check["model_identity_bound"]
            ):
                raise ValueError(
                    "Unsigned or unauthenticated model identity requires an explicit --model id@revision declaration"
                )
            model = declared or claimed
            if validation_model is not None and model != validation_model:
                raise ValueError(
                    "Declared aggregation model differs from the external-validation model"
                )
            count = _count(evaluation.get("sample_counts", {}).get("n_samples"))
            estimate = _finite(
                evaluation.get("metrics", {}).get(chosen_metric), "selected metric"
            )
            uncertainty = evaluation.get("uncertainty", {})
            interval = (
                uncertainty.get("metrics", {}).get(chosen_metric, {})
                if mode == "none"
                and uncertainty.get("metric_basis")
                in {"clean_metrics", "reported_metrics"}
                else {}
            )
            _add_site(
                groups,
                model,
                site,
                count,
                estimate,
                interval,
                mode,
                uncertainty.get("confidence_level"),
                _population_units(count, uncertainty, interval),
            )
        else:
            if len(parsed_models) != 2 or parsed_models[0] == parsed_models[1]:
                raise ValueError(
                    "Paired receipts require distinct --model A@revision --model B@revision declarations"
                )
            if evaluation.get("metric") != chosen_metric:
                raise ValueError(
                    "Paired artifact metric conflicts with selected protocol metric"
                )
            count = _count(evaluation.get("n_samples"))
            a, b = (
                _finite(evaluation.get(key, {}).get("selected_metric"), key)
                for key in ("model_a", "model_b")
            )
            improvement = (
                b - a
                if METRIC_DIRECTIONS[chosen_metric] == "lower_is_better"
                else a - b
            )
            if not math.isclose(
                improvement,
                _finite(evaluation.get("improvement_a_over_b"), "paired improvement"),
                rel_tol=1e-9,
                abs_tol=1e-12,
            ):
                raise ValueError("Paired improvement conflicts with per-model metrics")
            interval = evaluation.get("paired_interval", {})
            units = _population_units(
                count, interval, evaluation.get("randomization_test", {})
            )
            for model, value in zip(parsed_models, (a, b)):
                _add_site(groups, model, site, count, value, {}, "none", None, units)
            paired_sites.append(
                {
                    "site": site,
                    "n_samples": count,
                    "improvement_a_over_b": improvement,
                    "interval": interval,
                    **({"n_independent_units": units} if units is not None else {}),
                }
            )
        verification.append(
            {
                "input_number": index + 1,
                "payload_sha256": digest,
                "evidence_level": check["evidence_level"],
                "signer_trusted": check["signer_trusted"],
            }
        )
    site_sets = [set(site["site"] for site in rows) for rows in groups.values()]
    if (
        not site_sets
        or any(site_set != site_sets[0] for site_set in site_sets)
        or len(site_sets[0]) < 2
    ):
        raise ValueError(
            "Every model must cover the same set of at least two sites; missing sites cannot be silently dropped"
        )
    model_groups = []
    for model_key, rows in sorted(groups.items()):
        rows.sort(key=lambda row: row["site"])
        model_groups.append(
            {
                "model": {"id": model_key[0], "revision": model_key[1]},
                "sites": rows,
                "summary": summarize_sites(
                    rows,
                    chosen_metric,
                    disjoint=assume_disjoint_sites,
                    range_threshold=range_threshold,
                ),
            }
        )
    shared = {
        "protocol": compatibility["protocol"],
        "task_type": compatibility["task_type"],
        "metric": chosen_metric,
        "input_family": kind,
        "assume_disjoint_sites": assume_disjoint_sites,
        "range_threshold": range_threshold,
        "models": model_groups,
        "paired_sites": paired_sites,
        "paired_models": parsed_models if paired_sites else [],
        "limitations": LIMITATIONS,
    }
    return attach_integrity_metadata(
        {
            "schema_version": AGGREGATE_SCHEMA,
            "scope": "local",
            "shareable": shared,
            "local": {
                "input_verification": verification,
                "benchmark_identity": compatibility["benchmark"],
            },
        }
    )


def _add_site(
    groups, model, site, count, estimate, interval, mode, confidence, units=None
):
    from privatelabbench.privacy.export import _statistics

    key = (model["id"], model["revision"])
    rows = groups.setdefault(key, [])
    if any(row["site"] == site for row in rows):
        raise ValueError("Duplicated site for the same model")
    rows.append(
        {
            "site": site,
            "n_samples": count,
            "estimate": estimate,
            "interval": _statistics(interval),
            "confidence_level": confidence,
            "privacy_mode": mode,
            **({"n_independent_units": units} if units is not None else {}),
        }
    )


def sanitize_aggregate(
    shared: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Rebuild the public summary from approved scalars; plugin dictionaries stay local."""
    from privatelabbench.privacy.export import (
        _release_statistics,
        _token,
        protocol_identity,
    )

    if policy.get("include_protocol") is not True:
        raise ValueError(
            "Aggregate release requires explicit approval to include protocol identity"
        )
    protocol = protocol_identity(shared.get("protocol"))
    metric = shared.get("metric")
    if metric not in protocol["metrics"] or shared.get("task_type") not in {
        "regression",
        "classification",
        "multiclass",
    }:
        raise ValueError("Invalid aggregate metric/task")
    disjoint = shared.get("assume_disjoint_sites")
    if type(disjoint) is not bool:
        raise ValueError("Invalid site disjointness declaration")
    range_threshold = shared.get("range_threshold")
    if range_threshold is not None and _finite(range_threshold, "range_threshold") < 0:
        raise ValueError("range_threshold must be nonnegative")
    models = shared.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("Aggregate needs model/site data")
    approved_sites = set(policy.get("public_sites", []))
    approved_models = {
        tuple(model_identity(item).values()) for item in policy.get("public_models", [])
    }
    clean_models, seen_models, site_set = [], set(), None
    for item in models:
        model = model_identity(item.get("model"))
        key = (model["id"], model["revision"])
        if key not in approved_models or key in seen_models:
            raise ValueError(
                "Every model identity must be explicitly approved exactly once"
            )
        seen_models.add(key)
        rows = []
        for site in item["sites"]:
            label = _token(site.get("site"))
            count = _count(site.get("n_samples"))
            if (
                count < policy["min_cell_size"]
                or label not in approved_sites
                or any(row["site"] == label for row in rows)
            ):
                raise ValueError("Unapproved, small, or duplicated site")
            mode = site.get("privacy_mode", "none")
            if mode not in {"none", "metric_perturbation"}:
                raise ValueError("Invalid metric privacy basis")
            raw_interval = site.get("interval", {})
            units = _population_units(count, site, raw_interval)
            _require_population_floor(units, policy)
            interval = (
                _release_statistics(raw_interval, policy) if mode == "none" else {}
            )
            confidence = site.get("confidence_level")
            if (
                confidence is not None
                and not 0 < _finite(confidence, "confidence_level") < 1
            ):
                raise ValueError("Invalid site confidence level")
            rows.append(
                {
                    "site": label,
                    "n_samples": count,
                    "estimate": _finite(site.get("estimate"), "estimate"),
                    "interval": interval,
                    "confidence_level": confidence,
                    "privacy_mode": mode,
                    **({"n_independent_units": units} if units is not None else {}),
                }
            )
        labels = {row["site"] for row in rows}
        if site_set is not None and labels != site_set:
            raise ValueError("Models must cover identical sites")
        site_set = labels
        summary = summarize_sites(
            rows, metric, disjoint=disjoint, range_threshold=range_threshold
        )
        if summary["total_samples"] < policy["min_samples"]:
            raise ValueError("Aggregate sample count below policy minimum")
        clean_models.append({"model": model, "sites": rows, "summary": summary})
    paired_sites = []
    paired_models = shared.get("paired_models", [])
    if shared.get("paired_sites"):
        paired_models = [model_identity(model) for model in paired_models]
        if (
            len(paired_models) != 2
            or len(seen_models) != 2
            or set(tuple(model.values()) for model in paired_models) != seen_models
        ):
            raise ValueError("Invalid paired model declarations")
        for site in shared["paired_sites"]:
            label = _token(site.get("site"))
            if label not in site_set or any(
                row["site"] == label for row in paired_sites
            ):
                raise ValueError("Paired site must match the approved model/site set")
            count = _count(site.get("n_samples"))
            interval = site.get("interval", {})
            units = _population_units(count, site, interval)
            _require_population_floor(units, policy)
            model_sites = [
                row
                for model in clean_models
                for row in model["sites"]
                if row["site"] == label
            ]
            if any(
                row["n_samples"] != count
                or row.get("n_independent_units") is not None
                and row["n_independent_units"] != units
                for row in model_sites
            ):
                raise ValueError(
                    "Paired population counts differ from the model/site records"
                )
            if units is not None:
                # Older paired aggregate files retained units only on the interval.
                for row in model_sites:
                    row["n_independent_units"] = units
            paired_sites.append(
                {
                    "site": label,
                    "n_samples": count,
                    "improvement_a_over_b": _finite(
                        site.get("improvement_a_over_b"), "paired improvement"
                    ),
                    "interval": _release_statistics(interval, policy),
                    **({"n_independent_units": units} if units is not None else {}),
                }
            )
        if set(row["site"] for row in paired_sites) != site_set:
            raise ValueError("Paired comparisons must cover all sites")
    else:
        paired_models = []
    if shared.get("input_family") not in {
        "evaluation-receipt/v1",
        "paired-comparison-artifact/v1",
    }:
        raise ValueError("Unsupported aggregate input family")
    return {
        "protocol": protocol,
        "task_type": shared["task_type"],
        "metric": metric,
        "input_family": shared["input_family"],
        "assume_disjoint_sites": disjoint,
        "range_threshold": range_threshold,
        "models": clean_models,
        "paired_sites": paired_sites,
        "paired_models": paired_models,
        "limitations": LIMITATIONS,
    }


def render_aggregate(artifact: Mapping[str, Any]) -> str:
    shared = artifact["shareable"]
    protocol = shared["protocol"]
    lines = [
        "# Cross-site evaluation",
        "",
        f"Protocol: {protocol['id']}@{protocol['version']} (SHA-256 {protocol['sha256']})",
        f"Metric: {shared['metric']}",
        "",
    ]
    for model in shared["models"]:
        lines += [
            f"## {model['model']['id']}@{model['model']['revision']}",
            "",
            "| Site | N | Estimate | Site interval |",
            "| --- | ---: | ---: | --- |",
        ]
        for row in model["sites"]:
            interval = row["interval"]
            text = (
                f"[{interval['lower']:.6g}, {interval['upper']:.6g}]"
                if interval.get("lower") is not None
                and interval.get("upper") is not None
                else "unavailable"
            )
            lines.append(
                f"| {row['site']} | {row['n_samples']} | {row['estimate']:.6g} | {text} |"
            )
        summary = model["summary"]
        lines += [
            "",
            f"Site range: {summary['range']['absolute']:.6g}; worst site(s): {', '.join(summary['range']['worst_sites'])}.",
            f"Pooling: {summary['pooled']['status']}; estimate: {summary['pooled']['estimate']}.",
            "",
        ]
    if shared["paired_sites"]:
        lines += [
            "## Paired site evidence",
            "",
            "Positive improvement favors the first declared model. Intervals retain the site's paired design.",
            "",
        ]
        for row in shared["paired_sites"]:
            interval = row["interval"]
            lines.append(
                f"- {row['site']}: improvement {row['improvement_a_over_b']:.6g}; paired interval {interval.get('lower')} to {interval.get('upper')} ({interval.get('status', 'unavailable')})."
            )
    lines += ["## Limits", "", *[f"- {item}" for item in LIMITATIONS]]
    return "\n".join(lines) + "\n"

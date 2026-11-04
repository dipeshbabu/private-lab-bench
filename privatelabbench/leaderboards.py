"""Receipt-only hidden-benchmark tables with explicit protocol ranking rules."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from privatelabbench.eval.metrics import METRIC_DIRECTIONS
from privatelabbench.hidden_benchmarks import sanitize_submission, submission_identity
from privatelabbench.privacy.export import _mapping, protocol_identity
from privatelabbench.protocols import EvaluationProtocol, resolve_protocol
from privatelabbench.reports.integrity import attach_integrity_metadata, verify_payload
from privatelabbench.reports.receipt import validate_receipt_shape

SCHEMA = "benchmark-leaderboard/v1"


def _number(value):
    return (
        float(value) if type(value) in {float, int} and math.isfinite(value) else None
    )


def _interval(value, metric, point, mode):
    if (
        mode != "none"
        or not isinstance(value, Mapping)
        or not isinstance(value.get("metrics"), Mapping)
    ):
        return None
    item = value["metrics"].get(metric)
    if (
        not isinstance(item, Mapping)
        or item.get("status") != "evaluated"
        or value.get("metric_basis", "clean_metrics") != "clean_metrics"
    ):
        return None
    lower, upper, level, estimate = (
        _number(item.get("lower")),
        _number(item.get("upper")),
        _number(value.get("confidence_level")),
        _number(item.get("estimate")),
    )
    if (
        any(number is None for number in (lower, upper, level, estimate, point))
        or lower > upper
        or not 0 < level < 1
        or not math.isclose(estimate, point, rel_tol=1e-10, abs_tol=1e-12)
    ):
        return None
    return {"lower": lower, "upper": upper, "confidence_level": level}


def rank_rows(rows, rules, metric):
    rows = [{**row, "rank_group": None} for row in rows]

    def label(row):
        return (
            row["submission"]["model"]["id"],
            row["submission"]["model"]["revision"],
            row["submission"]["id"],
        )

    if rules is None:
        return sorted(rows, key=label), "not_declared_in_protocol"
    if any(row["estimate"] is None for row in rows):
        return sorted(rows, key=label), "estimate_unavailable"
    if rules["require_uncertainty"] and any(
        row.get("interval") is None for row in rows
    ):
        return sorted(rows, key=label), "uncertainty_unavailable"
    sign = 1 if METRIC_DIRECTIONS[metric] == "lower_is_better" else -1
    intervals = []
    for row in rows:
        point = sign * row["estimate"]
        interval = row.get("interval") if rules["require_uncertainty"] else None
        lower, upper = (
            (interval["lower"], interval["upper"])
            if interval
            else (row["estimate"], row["estimate"])
        )
        if sign < 0:
            lower, upper = -upper, -lower
        # Widen rather than make a stronger claim if a percentile interval excludes its point.
        intervals.append((min(lower, point), max(upper, point), point, label(row), row))
    intervals.sort(key=lambda item: (item[0], item[2], item[3]))
    groups = []
    frontier = None
    for lower, upper, point, identity, row in intervals:
        if frontier is None or lower > frontier + rules["practical_tie_tolerance"]:
            groups.append([])
            frontier = upper
        else:
            frontier = max(frontier, upper)
        groups[-1].append(row)
    ranked = []
    for index, group in enumerate(groups, start=1):
        for row in sorted(group, key=lambda row: (sign * row["estimate"], label(row))):
            ranked.append({**row, "rank_group": index})
    return ranked, (
        "conservative_interval_groups"
        if rules["require_uncertainty"]
        else "descriptive_point_groups"
    )


def build_leaderboard(
    paths,
    protocol,
    *,
    signing_secret=None,
    trust_store=None,
    require_trusted_signer=False,
):
    if not 1 <= len(paths) <= 1000:
        raise ValueError("Supply 1–1000 shareable submission receipts")
    definition = resolve_protocol(str(protocol))
    rules = definition.as_dict()
    metric = (
        rules["ranking"]["metric"] if rules.get("ranking") else rules["primary_metric"]
    )
    rows, verification, seen, models, compatibility = [], [], set(), set(), None
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "evaluation-receipt/v1"
            or payload.get("scope") != "shareable"
            or "local" in payload
        ):
            raise ValueError(
                "Leaderboards consume already-shareable submission receipts only"
            )
        validate_receipt_shape(payload)
        check = verify_payload(
            payload,
            signing_secret=signing_secret,
            trust_store=trust_store,
            require_trusted_signer=require_trusted_signer,
            expected_protocol_sha256=(
                definition.sha256 if require_trusted_signer else None
            ),
        )
        if not check["valid"]:
            raise ValueError("Submission receipt failed verification")
        shared = _mapping(payload["shareable"])
        evaluation = _mapping(shared["evaluation"])
        if protocol_identity(evaluation.get("protocol")) != definition.identity():
            raise ValueError(
                "Submission protocol differs from the selected ranking definition"
            )
        metadata = submission_identity(evaluation.get("benchmark_submission"))
        claimed = _mapping(payload.get("signer_statement", {})).get("model")
        if claimed is not None and claimed != metadata["model"]:
            raise ValueError("Submission model conflicts with its signer statement")
        privacy = _mapping(shared.get("privacy"))
        release = _mapping(privacy.get("release"))
        if (
            release.get("decision") != "allow"
            or release.get("status") != "pass"
            or release.get("publishable") is not True
        ):
            raise ValueError(
                "Every submission needs a successful owner release decision"
            )
        n = _mapping(evaluation.get("sample_counts")).get("n_samples")
        units = _mapping(evaluation.get("uncertainty", {})).get("n_independent_units")
        if (
            type(n) is not int
            or n < 2
            or units is not None
            and (type(units) is not int or not 2 <= units <= n)
        ):
            raise ValueError("Invalid submission sample/unit count")
        benchmark = _mapping(shared.get("benchmark"))
        if not benchmark.get("id") or not benchmark.get("version"):
            raise ValueError("Exact owner benchmark identity is required")
        mode = _mapping(privacy.get("mechanism", {})).get("mode", "none")
        key = {
            "benchmark": dict(benchmark),
            "task_type": evaluation.get("task_type"),
            "n_samples": n,
            "privacy_mode": mode,
        }
        if (
            key["task_type"] != rules["task_type"]
            or mode not in {"none", "metric_perturbation"}
            or evaluation.get("metric_source") != "reported_metrics"
            or _mapping(evaluation.get("input_schema", {})).get("schema_version")
            != "prediction-table/v1"
            or compatibility is not None
            and compatibility != key
        ):
            raise ValueError(
                "Submissions differ in benchmark/task/test count/metric basis"
            )
        compatibility = key
        model_key = tuple(metadata["model"].values())
        if (
            metadata["id"] in seen
            or check["payload_sha256"] in seen
            or model_key in models
        ):
            raise ValueError("Duplicate submission, model revision, or receipt")
        seen.update((metadata["id"], check["payload_sha256"]))
        models.add(model_key)
        point = _number(_mapping(evaluation.get("metrics")).get(metric))
        rows.append(
            {
                "submission": metadata,
                "n_samples": n,
                "n_independent_units": units,
                "estimate": point,
                "interval": _interval(
                    evaluation.get("uncertainty"), metric, point, mode
                ),
                "source_receipt_sha256": check["payload_sha256"],
            }
        )
        verification.append(
            {
                "payload_sha256": check["payload_sha256"],
                "evidence_level": check["evidence_level"],
                "signer_trusted": check["signer_trusted"],
            }
        )
    rows, status = rank_rows(rows, rules.get("ranking"), metric)
    shared = {
        **compatibility,
        "protocol": definition.identity(),
        "metric": metric,
        "ranking_rules": rules.get("ranking"),
        "ranking_status": status,
        "rows": rows,
        "comparison_scope": "marginal_receipt_intervals_not_paired_tests",
        "multiplicity": "exploratory_unadjusted",
    }
    artifact = {
        "schema_version": SCHEMA,
        "leaderboard_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local",
        "shareable": shared,
        "local": {
            "protocol_definition": rules,
            "input_verification": verification,
            "limitations": [
                "Receipt hashes do not authenticate an owner or independently prove execution; pin trusted owner signers when needed.",
                "Ranking uses only an explicitly declared protocol rule. Marginal interval groups are conservative and can connect transitively; they do not prove equality or paired statistical significance.",
                "Test-set identity and honest execution remain owner declarations; this is not a complete anti-cheating or secure model execution system.",
            ],
        },
    }
    return attach_integrity_metadata(artifact, signing_secret=signing_secret)


def sanitize_leaderboard(value, policy, definition):
    shared = _mapping(value)
    definition = EvaluationProtocol.from_dict(definition)
    if protocol_identity(shared.get("protocol")) != definition.identity() or shared.get(
        "ranking_rules"
    ) != definition.as_dict().get("ranking"):
        raise ValueError(
            "Leaderboard ranking rule differs from its full pinned protocol definition"
        )
    if not policy.get("include_protocol") or not policy.get("include_submission"):
        raise ValueError(
            "Leaderboard release requires explicit protocol and submission approval"
        )
    benchmark = _mapping(shared.get("benchmark"))
    approved = _mapping(policy.get("public_benchmark", {}))
    if any(
        not approved.get(key) or approved[key] != benchmark.get(key)
        for key in ("id", "version")
    ) or any(benchmark.get(key) != item for key, item in approved.items()):
        raise ValueError("Approve the exact hidden benchmark identity")
    rules = definition.as_dict()
    metric = (
        rules["ranking"]["metric"] if rules.get("ranking") else rules["primary_metric"]
    )
    if (
        shared.get("metric") != metric
        or shared.get("task_type") != rules["task_type"]
        or shared.get("privacy_mode") not in {"none", "metric_perturbation"}
    ):
        raise ValueError("Invalid leaderboard scientific basis")
    values = shared.get("rows")
    if not isinstance(values, list) or not 1 <= len(values) <= 1000:
        raise ValueError("A leaderboard needs a bounded nonempty row list")
    rows, seen, models = [], set(), set()
    for value in values:
        value = _mapping(value)
        metadata = sanitize_submission(value.get("submission"), policy)
        model_key = tuple(metadata["model"].values())
        if metadata["id"] in seen or model_key in models:
            raise ValueError("Duplicate leaderboard identity")
        seen.add(metadata["id"])
        models.add(model_key)
        n, units = value.get("n_samples"), value.get("n_independent_units")
        if (
            type(n) is not int
            or n < policy["min_samples"]
            or n != shared.get("n_samples")
        ):
            raise ValueError(
                "Every submission must satisfy the test-set release minimum"
            )
        if units is not None and (
            type(units) is not int
            or not max(policy["min_samples"], policy["min_cell_size"]) <= units <= n
        ):
            raise ValueError("Submission independent-unit count is below policy")
        point = _number(value.get("estimate"))
        interval = None
        if value.get("interval") is not None and shared["privacy_mode"] == "none":
            item = _mapping(value["interval"])
            lower, upper, level = (
                _number(item.get(key)) for key in ("lower", "upper", "confidence_level")
            )
            if (
                any(item is None for item in (lower, upper, level))
                or lower > upper
                or not 0 < level < 1
            ):
                raise ValueError("Invalid leaderboard interval")
            interval = {"lower": lower, "upper": upper, "confidence_level": level}
        row = {
            "submission": metadata,
            "n_samples": n,
            "n_independent_units": units,
            "estimate": point,
            "interval": interval,
        }
        if policy.get("include_source_receipts"):
            from privatelabbench.hidden_benchmarks import DIGEST

            digest = value.get("source_receipt_sha256")
            if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
                raise ValueError("Invalid source receipt digest")
            row["source_receipt_sha256"] = digest
        rows.append(row)
    rows, status = rank_rows(rows, rules.get("ranking"), metric)
    return {
        "benchmark": dict(approved),
        "task_type": rules["task_type"],
        "n_samples": shared["n_samples"],
        "privacy_mode": shared["privacy_mode"],
        "protocol": definition.identity(),
        "metric": metric,
        "ranking_rules": rules.get("ranking"),
        "ranking_status": status,
        "rows": rows,
        "comparison_scope": "marginal_receipt_intervals_not_paired_tests",
        "multiplicity": "exploratory_unadjusted",
    }


def render_leaderboard(artifact):
    shared = artifact["shareable"]
    lines = [
        "# Hidden benchmark results",
        "",
        f"Benchmark: {shared['benchmark']['id']}@{shared['benchmark']['version']}",
        f"Metric: {shared['metric']}; ranking status: {shared['ranking_status']}",
        "",
        "| Rank group | Submission | Model | N | Estimate | Marginal interval |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in shared["rows"]:
        submission = row["submission"]
        interval = row.get("interval")
        bounds = (
            f"[{interval['lower']:.6g}, {interval['upper']:.6g}]"
            if interval
            else "unavailable"
        )
        point = (
            f"{row['estimate']:.6g}" if row["estimate"] is not None else "unavailable"
        )
        lines.append(
            f"| {row.get('rank_group') or 'unranked'} | {submission['id']} | {submission['model']['id']}@{submission['model']['revision']} | {row['n_samples']} | {point} | {bounds} |"
        )
    lines.extend(
        [
            "",
            "Rank groups follow only the explicit pinned protocol rule. Conservative interval/tolerance ties can connect transitively and do not establish equality, paired significance, or simultaneous coverage. Use owner-side paired comparisons when raw predictions are available. Receipt integrity alone does not authenticate honest execution.",
        ]
    )
    return "\n".join(lines) + "\n"


def leaderboard_command(args):
    import yaml

    from privatelabbench.privacy.export import (
        atomic_write_json,
        publish_shareable_artifact,
    )

    output = Path(args.out).resolve()
    public = output.with_name(output.stem + ".shareable.json")
    markdown = output.with_suffix(".md")
    sources = {
        Path(path).resolve()
        for path in [*args.inputs, args.release_policy, args.trust_store]
        if path
    }
    if not args.protocol.startswith("plb://"):
        sources.add(Path(args.protocol).resolve())
    targets = [
        output,
        public,
        markdown,
        public.with_suffix(".release-audit.json"),
        output.parent / ".plb-release-ledger.json",
        output.parent / ".plb-release.lock",
    ]
    from privatelabbench.core.local_io import validate_output_paths

    try:
        validate_output_paths(sources, targets)
    except (ValueError, OSError) as exc:
        print(f"Leaderboard rejected: {exc}")
        return 2
    public.unlink(missing_ok=True)
    markdown.unlink(missing_ok=True)
    try:
        trust = (
            yaml.safe_load(Path(args.trust_store).read_text(encoding="utf-8"))
            if args.trust_store
            else None
        )
        artifact = build_leaderboard(
            args.inputs,
            args.protocol,
            signing_secret=args.signing_secret,
            trust_store=trust,
            require_trusted_signer=args.require_trusted_signer,
        )
        atomic_write_json(output, artifact)
        policy = (
            yaml.safe_load(Path(args.release_policy).read_text(encoding="utf-8"))
            if args.release_policy
            else None
        )
        decision = publish_shareable_artifact(
            artifact, policy, public, signing_secret=args.signing_secret
        )
        if decision.decision == "allow":
            markdown.write_text(
                render_leaderboard(json.loads(public.read_text(encoding="utf-8"))),
                encoding="utf-8",
            )
        print(
            f"Local leaderboard: {output}; ranking status: {artifact['shareable']['ranking_status']}"
        )
        print(f"Release: {decision.decision}")
        return 0
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError):
        public.unlink(missing_ok=True)
        markdown.unlink(missing_ok=True)
        print(
            "Leaderboard rejected. Check receipt verification, exact protocol/benchmark identities, and owner release approval."
        )
        return 2

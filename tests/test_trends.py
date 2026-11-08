import json
from pathlib import Path

import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.privacy.export import check_release
from privatelabbench.protocols import resolve_protocol
from privatelabbench.reports.integrity import attach_integrity_metadata, verify_payload
from privatelabbench.trends import render_trend, trend_receipts

MODEL = {"id": "synthetic-model", "revision": "v1"}
SERIES = {"id": "synthetic-monthly", "revision": "v1"}


def receipts(tmp_path, values, *, width=0.02):
    paths, times = [], []
    protocol = resolve_protocol("plb://generic/regression@1.0.0").identity()
    for index, value in enumerate(values):
        n = 120
        payload = {
            "schema_version": "evaluation-receipt/v1",
            "receipt_id": f"synthetic-{index}",
            "scope": "shareable",
            "shareable": {
                "run": {},
                "benchmark": {},
                "evaluation": {
                    "task_type": "regression",
                    "sample_counts": {"n_samples": n},
                    "input_schema": {"schema_version": "prediction-table/v1"},
                    "metrics": {"rmse": value},
                    "metric_source": "reported_metrics",
                    "protocol": protocol,
                    "uncertainty": {
                        "status": "evaluated",
                        "metric_basis": "clean_metrics",
                        "confidence_level": 0.95,
                        "metrics": {
                            "rmse": {
                                "status": "evaluated",
                                "estimate": value,
                                "lower": value - width,
                                "upper": value + width,
                            }
                        },
                    },
                    "slices": {
                        "site": {
                            "a": {
                                "status": "evaluated",
                                "n_samples": 60,
                                "metrics": {"rmse": value},
                            },
                            "b": {
                                "status": "evaluated",
                                "n_samples": 60,
                                "metrics": {"rmse": value * 1.2},
                            },
                        }
                    },
                    "quality_gate": {
                        "schema_version": "quality-gate/v1",
                        "status": "pass",
                    },
                },
                "privacy": {
                    "mechanism": {"mode": "none"},
                    "release": {
                        "status": "pass",
                        "publishable": True,
                        "decision": "allow",
                    },
                },
                "provenance": {},
                "artifacts": [],
            },
        }
        path = tmp_path / f"receipt-{index}.json"
        path.write_text(json.dumps(attach_integrity_metadata(payload)))
        paths.append(path)
        times.append(f"2026-{index + 1:02d}-01")
    return paths, times


def trend(paths, times, **options):
    options.setdefault("metric", "rmse")
    return trend_receipts(paths, times=times, series=SERIES, model=MODEL, **options)


def edit(path, change):
    payload = json.loads(path.read_text())
    change(payload)
    path.write_text(json.dumps(attach_integrity_metadata(payload)))


def policy(times):
    return {
        "schema_version": "release-policy/v1",
        "id": "reviewed-series",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "public_series": SERIES,
        "public_models": [MODEL],
        "public_times": times,
        "include_quality_gate": True,
        "include_source_receipts": True,
        "slices": {"site": ["a", "b"]},
    }


@pytest.mark.parametrize(
    "time", [None, 20260101, "2026-01-01T12:00:00", "2026-13-01", "invalid"]
)
def test_bad_collection_times_are_not_inferred_or_silently_reordered(tmp_path, time):
    paths, times = receipts(tmp_path, [0.2, 0.3])
    with pytest.raises(ValueError):
        trend(paths, [time, times[1]])


@pytest.mark.parametrize("count", [-1, 121, True])
def test_semantically_invalid_slice_counts_fail_after_source_integrity_passes(
    tmp_path, count
):
    paths, times = receipts(tmp_path, [0.2, 0.3])
    edit(
        paths[1],
        lambda payload: payload["shareable"]["evaluation"]["slices"]["site"][
            "a"
        ].update(n_samples=count),
    )
    with pytest.raises(ValueError, match="slice count"):
        trend(paths, times)


@pytest.mark.parametrize(
    "damage",
    [
        "reference",
        "threshold",
        "prevalence",
        "source_digest",
        "quality",
        "diagnostic",
        "all_undefined",
    ],
)
def test_destination_trend_policy_rejects_invalid_rebuilt_evidence(tmp_path, damage):
    paths, times = receipts(tmp_path, [0.2, 0.3])
    artifact = trend(paths, times)
    shared = artifact["shareable"]
    if damage == "reference":
        shared["reference_index"] = True
    elif damage == "threshold":
        shared["practical_threshold"] = -1
    elif damage == "prevalence":
        shared["prevalence_threshold"] = 2
    elif damage == "source_digest":
        shared["periods"][0]["source_receipt_sha256"] = "not-a-digest"
    elif damage == "quality":
        shared["periods"][0]["quality_gate"] = "unknown"
    elif damage == "diagnostic":
        shared["periods"][0]["cohort_diagnostics"] = "unknown"
    else:
        for period in shared["periods"]:
            period["estimate"] = None
    decision, public = check_release(
        artifact, {**policy(times), "include_degradation": True}
    )
    assert decision.decision != "allow" and public is None


@pytest.mark.parametrize(
    "values,last",
    [
        ([0.2, 0.2, 0.2], "within_threshold"),
        ([0.2, 0.25, 0.3], "degradation"),
        ([0.2, 0.2, 0.8], "degradation"),
        ([0.2, 0.8, 0.2], "within_threshold"),
    ],
)
def test_stable_gradual_abrupt_and_recovery_sequences(tmp_path, values, last):
    paths, times = receipts(tmp_path, values)
    artifact = trend(paths, times, practical_threshold=0.01)
    assert verify_payload(artifact)["valid"]
    periods = artifact["shareable"]["periods"]
    assert periods[-1]["from_reference"]["point_change"] == last
    assert periods[-1]["from_previous"]["raw_delta"] == pytest.approx(
        values[-1] - values[-2]
    )
    assert periods[0]["from_reference"]["difference_bounds"]["lower"] == 0
    assert artifact["shareable"]["causal_drift_claim"] is False
    assert len(artifact["local"]["sources"]) == 3


def test_small_sampling_changes_are_not_labeled_confident_drift(tmp_path):
    paths, times = receipts(tmp_path, [0.2, 0.21], width=0.1)
    artifact = trend(paths, times, practical_threshold=0.001)
    change = artifact["shareable"]["periods"][1]["from_reference"]
    assert change["point_change"] == "degradation"
    assert change["uncertainty_assessment"] == "compatible_with_no_material_change"
    assert change["difference_bounds"][
        "marginal_coverage_union_bound"
    ] == pytest.approx(0.9)
    assert change["difference_bounds"]["joint_resampling"] is False


def test_missing_intervals_and_zero_reference_stay_explicit(tmp_path):
    paths, times = receipts(tmp_path, [0.0, 0.3])
    edit(paths[1], lambda p: p["shareable"]["evaluation"].update({"uncertainty": {}}))
    change = trend(paths, times)["shareable"]["periods"][1]["from_reference"]
    assert change["relative_degradation"] is None
    assert change["uncertainty_assessment"] == "unavailable"


@pytest.mark.parametrize(
    "damage",
    ["digest", "protocol", "task", "model", "privacy", "release", "duplicate", "time"],
)
def test_incompatible_or_invalid_sources_rejected(tmp_path, damage):
    paths, times = receipts(tmp_path, [0.2, 0.3])
    if damage == "digest":
        payload = json.loads(paths[1].read_text())
        payload["shareable"]["evaluation"]["metrics"]["rmse"] = 0.4
        paths[1].write_text(json.dumps(payload))
    elif damage == "protocol":
        edit(
            paths[1],
            lambda p: p["shareable"]["evaluation"]["protocol"].update(
                {"sha256": "a" * 64}
            ),
        )
    elif damage == "task":
        edit(
            paths[1],
            lambda p: p["shareable"]["evaluation"].update(
                {"task_type": "classification"}
            ),
        )
    elif damage == "model":
        edit(
            paths[1],
            lambda p: p.update(
                {"signer_statement": {"model": {"id": "other", "revision": "v1"}}}
            ),
        )
    elif damage == "privacy":
        edit(
            paths[1],
            lambda p: p["shareable"]["privacy"]["mechanism"].update(
                {"mode": "metric_perturbation"}
            ),
        )
    elif damage == "release":
        edit(
            paths[1],
            lambda p: p["shareable"]["privacy"]["release"].update({"decision": "deny"}),
        )
    elif damage == "duplicate":
        paths[1] = paths[0]
    else:
        times.reverse()
    with pytest.raises(ValueError):
        trend(paths, times)


def test_new_missing_slices_prevalence_and_critical_results(tmp_path):
    paths, times = receipts(tmp_path, [0.2, 0.5])

    def change(payload):
        groups = payload["shareable"]["evaluation"]["slices"]["site"]
        groups["a"]["n_samples"] = 90
        groups["c"] = groups.pop("b")
        groups["c"]["n_samples"] = 30

    edit(paths[1], change)
    period = trend(paths, times, critical_slices=[("site", "a")])["shareable"][
        "periods"
    ][1]
    rows = {item["value"]: item for item in period["slice_changes"]}
    assert rows["b"]["presence"] == "missing" and rows["c"]["presence"] == "new"
    assert rows["a"]["material_prevalence_change"] and rows["a"]["critical"]
    assert rows["a"]["from_reference"]["point_change"] == "degradation"


def test_recurring_quality_policy_uses_existing_gate(tmp_path):
    paths, times = receipts(tmp_path, [0.2, 0.5])
    quality = {
        "schema_version": "quality-policy/v1",
        "metric": {"rmse": {"max": 0.3}},
    }
    periods = trend(paths, times, quality_policy=quality)["shareable"]["periods"]
    assert [row["quality_gate"] for row in periods] == ["pass", "fail"]


def test_public_trend_recomputes_changes_and_requires_exact_approvals(tmp_path):
    paths, times = receipts(tmp_path, [0.2, 0.5])
    artifact = trend(paths, times)
    artifact["shareable"]["periods"][1]["from_reference"]["degradation"] = -100
    artifact["shareable"]["periods"][1]["inference_log"] = "private raw data"
    decision, public = check_release(artifact, policy(times))
    assert decision.decision == "allow"
    assert public["shareable"]["periods"][1]["from_reference"][
        "degradation"
    ] == pytest.approx(0.3)
    text = json.dumps(public)
    assert "private raw data" not in text and str(tmp_path) not in text
    assert "source_receipt_sha256" in text
    changed = policy(times)
    changed["public_times"] = ["2025-01-01", "2025-02-01"]
    assert check_release(artifact, changed)[1] is None
    changed = policy(times)
    changed["slices"] = {"site": ["a"]}
    assert check_release(artifact, changed)[1] is None
    assert "marginal" in render_trend(public)


def test_public_trend_blocks_small_periods_and_partial_partitions(tmp_path):
    paths, times = receipts(tmp_path, [0.2, 0.5])
    artifact = trend(paths, times)
    artifact["shareable"]["periods"][0]["n_samples"] = 5
    assert check_release(artifact, policy(times))[1] is None
    artifact = trend(paths, times)
    artifact["shareable"]["periods"][0]["slices"]["site"]["a"]["n_samples"] = 2
    assert check_release(artifact, policy(times))[1] is None


def test_cli_export_and_failed_rerun_clear_public_outputs(tmp_path, monkeypatch):
    paths, times = receipts(tmp_path, [0.2, 0.5])
    release = tmp_path / "release.yaml"
    release.write_text(yaml.safe_dump(policy(times)))
    output = tmp_path / "trend.json"
    args = [
        "plb",
        "trend",
        *map(str, paths),
        "--time",
        times[0],
        "--time",
        times[1],
        "--series",
        "synthetic-monthly@v1",
        "--model",
        "synthetic-model@v1",
        "--metric",
        "rmse",
        "--release-policy",
        str(release),
        "--out",
        str(output),
    ]
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    public = tmp_path / "trend.shareable.json"
    assert public.exists() and verify_payload(json.loads(public.read_text()))["valid"]
    paths[1].write_text("not JSON")
    assert main() == 2
    assert not public.exists() and not output.with_suffix(".md").exists()


def test_higher_is_better_changes_keep_the_correct_direction(tmp_path):
    paths, times = receipts(tmp_path, [0.8, 0.7])
    protocol = resolve_protocol("plb://generic/binary@1.0.1").identity()

    def change(payload):
        evaluation = payload["shareable"]["evaluation"]
        evaluation["task_type"] = "classification"
        evaluation["protocol"] = protocol
        evaluation["metrics"] = {"auroc": evaluation["metrics"]["rmse"]}
        evaluation["uncertainty"]["metrics"] = {
            "auroc": evaluation["uncertainty"]["metrics"]["rmse"]
        }

    for path in paths:
        edit(path, change)
    change = trend(paths, times, metric="auroc")["shareable"]["periods"][1][
        "from_reference"
    ]
    assert change["raw_delta"] == pytest.approx(-0.1)
    assert change["degradation"] == pytest.approx(0.1)
    assert change["difference_bounds"]["lower"] > 0


def test_new_release_floors_apply_to_every_period_and_slice_sampling_unit(tmp_path):
    paths, times = receipts(tmp_path, [0.2, 0.5])

    def change(payload):
        evaluation = payload["shareable"]["evaluation"]
        evaluation["uncertainty"]["n_independent_units"] = 30
        evaluation["slices"]["site"]["a"]["uncertainty"] = {"n_independent_units": 3}

    edit(paths[1], change)
    artifact = trend(paths, times)
    assert check_release(artifact, policy(times))[1] is None
    approved = policy(times)
    approved["slices"] = {}
    assert check_release(artifact, approved)[0].decision == "allow"
    approved["min_samples"] = 40
    assert check_release(artifact, approved)[1] is None


def test_latest_quality_gate_can_recover_after_a_past_failure(tmp_path, monkeypatch):
    paths, times = receipts(tmp_path, [0.2, 0.8, 0.2])
    quality = tmp_path / "quality.yaml"
    quality.write_text(
        yaml.safe_dump(
            {"schema_version": "quality-policy/v1", "metric": {"rmse": {"max": 0.3}}}
        )
    )
    args = [
        "plb",
        "trend",
        *map(str, paths),
        "--series",
        "study@v1",
        "--model",
        "synthetic-model@v1",
        "--metric",
        "rmse",
        "--quality-policy",
        str(quality),
        "--out",
        str(tmp_path / "trend.json"),
    ]
    for time in times:
        args.extend(["--time", time])
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    artifact = json.loads((tmp_path / "trend.json").read_text())
    assert [row["quality_gate"] for row in artifact["shareable"]["periods"]] == [
        "pass",
        "fail",
        "pass",
    ]


def test_longitudinal_and_release_schemas(tmp_path):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    import privatelabbench.trends as module

    paths, times = receipts(tmp_path, [0.2, 0.5])
    artifact = trend(paths, times)
    directory = Path(module.__file__).parent / "data/schemas"
    resources = []
    for path in directory.glob("*.schema.json"):
        value = json.loads(path.read_text())
        resource = Resource.from_contents(value)
        resources.append((path.name, resource))
        if "$id" in value:
            resources.append((value["$id"], resource))
    registry = Registry().with_resources(resources)
    schema = json.loads((directory / "longitudinal-series-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, registry=registry)
    validator.validate(artifact)
    decision, public = check_release(artifact, policy(times))
    assert decision.decision == "allow"
    validator.validate(attach_integrity_metadata(public))
    schema = json.loads((directory / "release-policy-v1.schema.json").read_text())
    Draft202012Validator(schema, registry=registry).validate(policy(times))


@pytest.mark.parametrize(
    "section", ["sample_counts", "slices", "input_schema", "external_validation"]
)
def test_malformed_source_sections_are_rejected(tmp_path, section):
    paths, times = receipts(tmp_path, [0.2, 0.5])
    edit(paths[1], lambda p: p["shareable"]["evaluation"].update({section: []}))
    with pytest.raises(ValueError):
        trend(paths, times)

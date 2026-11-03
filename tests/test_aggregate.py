from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from privatelabbench.aggregate import aggregate_receipts, summarize_sites
from privatelabbench.cli import main
from privatelabbench.privacy.export import check_release, publish_shareable_artifact
from privatelabbench.protocols import resolve_protocol
from privatelabbench.reports.integrity import (
    attach_integrity_metadata,
    verify_payload,
    verify_report,
)

MODEL = {"id": "published-model", "revision": "frozen-1"}


def receipt(
    tmp_path, name, *, n=20, mae=0.2, rmse=0.3, task="regression", protocol=None
):
    protocol = protocol or resolve_protocol("plb://generic/regression@1.0.0").identity()
    payload = {
        "schema_version": "evaluation-receipt/v1",
        "receipt_id": str(uuid4()),
        "scope": "shareable",
        "shareable": {
            "run": {},
            "benchmark": {},
            "evaluation": {
                "task_type": task,
                "input_schema": {"schema_version": "prediction-table/v1"},
                "protocol": protocol,
                "metrics": {"mae": mae, "rmse": rmse, "r2": 0.7},
                "sample_counts": {"n_samples": n},
                "metric_source": "reported_metrics",
                "uncertainty": {
                    "metric_basis": "clean_metrics",
                    "confidence_level": 0.95,
                    "metrics": {
                        "mae": {
                            "status": "evaluated",
                            "lower": mae * 0.8,
                            "upper": mae * 1.2,
                        }
                    },
                },
            },
            "privacy": {"mechanism": {"mode": "none"}},
            "provenance": {},
            "artifacts": [],
        },
    }
    payload["shareable"]["privacy"]["release"] = {
        "decision": "allow",
        "status": "pass",
        "publishable": True,
    }
    return write(tmp_path / f"{name}.json", payload)


def write(path, payload):
    path.write_text(json.dumps(attach_integrity_metadata(payload)))
    return path


def release(**extra):
    return {
        "schema_version": "release-policy/v1",
        "id": "reviewed-aggregate",
        "enabled": True,
        "min_samples": 20,
        "min_cell_size": 5,
        "require_privacy_audit": False,
        "include_protocol": True,
        "public_sites": ["site-1", "site-2"],
        "public_models": [MODEL],
        **extra,
    }


def test_exact_pooling_matches_raw_observation_identities_and_keeps_site_evidence(
    tmp_path,
):
    a = receipt(tmp_path, "private-filename-a", n=20, mae=0.1, rmse=0.2)
    b = receipt(tmp_path, "private-filename-b", n=60, mae=0.3, rmse=0.4)
    result = aggregate_receipts(
        [a, b], models=[MODEL], assume_disjoint_sites=True, range_threshold=0.15
    )
    group = result["shareable"]["models"][0]
    assert [row["site"] for row in group["sites"]] == ["site-1", "site-2"]
    assert group["sites"][0]["interval"]["lower"] == pytest.approx(0.08)
    assert group["summary"]["pooled"]["estimate"] == pytest.approx(
        (20 * 0.1 + 60 * 0.3) / 80
    )
    assert group["summary"]["range"]["worst_sites"] == ["site-2"]
    assert group["summary"]["range"]["material"] is True
    assert group["summary"]["pooled"]["confidence_interval"] is None
    result = aggregate_receipts(
        [a, b], models=[MODEL], metric="rmse", assume_disjoint_sites=True
    )
    assert result["shareable"]["models"][0]["summary"]["pooled"][
        "estimate"
    ] == pytest.approx(((20 * 0.2**2 + 60 * 0.4**2) / 80) ** 0.5)
    assert str(a) not in json.dumps(result["shareable"])


def test_nonlinear_metrics_and_unproven_disjointness_never_get_naive_pooled_scores(
    tmp_path,
):
    inputs = [receipt(tmp_path, "a"), receipt(tmp_path, "b")]
    result = aggregate_receipts(inputs, models=[MODEL])
    assert (
        result["shareable"]["models"][0]["summary"]["pooled"]["status"]
        == "requires_disjoint_sites_declaration"
    )
    result = aggregate_receipts(
        inputs, models=[MODEL], metric="r2", assume_disjoint_sites=True
    )
    assert result["shareable"]["models"][0]["summary"]["pooled"]["estimate"] is None
    rows = [
        {"site": "a", "n_samples": 20, "estimate": 0.8},
        {"site": "b", "n_samples": 60, "estimate": 0.6},
    ]
    for metric in ("auroc", "r2", "f1", "macro_f1", "weighted_f1", "macro_auroc_ovr"):
        assert (
            summarize_sites(rows, metric, disjoint=True)["pooled"]["status"]
            == "not_poolable_from_site_metrics"
        )
    for metric in ("accuracy", "log_loss"):
        assert summarize_sites(rows, metric, disjoint=True)["pooled"][
            "estimate"
        ] == pytest.approx(0.65)
    assert (
        summarize_sites(
            [{**row, "privacy_mode": "metric_perturbation"} for row in rows],
            "accuracy",
            disjoint=True,
        )["pooled"]["status"]
        == "not_poolable_from_perturbed_metrics"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "scope",
        "local",
        "protocol",
        "missing_protocol",
        "schema",
        "task",
        "metric",
        "count",
        "nan",
        "release_denied",
        "release_absent",
    ],
)
def test_bad_or_incompatible_receipts_rejected_before_aggregation(tmp_path, mutation):
    a, b = receipt(tmp_path, "a"), receipt(tmp_path, "b")
    payload = json.loads(b.read_text())
    evaluation = payload["shareable"]["evaluation"]
    if mutation == "hash":
        evaluation["metrics"]["mae"] = 1
        b.write_text(json.dumps(payload))
    else:
        if mutation == "scope":
            payload["scope"] = "local"
        if mutation == "local":
            payload["local"] = {"private": "sentinel"}
        if mutation == "protocol":
            evaluation["protocol"]["sha256"] = "b" * 64
        if mutation == "missing_protocol":
            evaluation.pop("protocol")
        if mutation == "schema":
            evaluation["input_schema"]["schema_version"] = "unknown"
        if mutation == "task":
            evaluation["task_type"] = "classification"
        if mutation == "metric":
            evaluation["metrics"].pop("mae")
        if mutation == "count":
            evaluation["sample_counts"]["n_samples"] = 0
        if mutation == "nan":
            evaluation["metrics"]["mae"] = float("nan")
        if mutation == "release_denied":
            payload["shareable"]["privacy"]["release"]["decision"] = "deny"
        if mutation == "release_absent":
            payload["shareable"]["privacy"].pop("release")
        write(b, payload)
    with pytest.raises(ValueError):
        aggregate_receipts([a, b], models=[MODEL])


def test_duplicates_missing_sites_and_model_ambiguity_are_explicit(tmp_path):
    inputs = [receipt(tmp_path, str(i)) for i in range(4)]
    with pytest.raises(ValueError, match="Duplicated"):
        aggregate_receipts([inputs[0], inputs[0]], models=[MODEL])
    with pytest.raises(ValueError, match="Duplicated site"):
        aggregate_receipts(inputs[:2], sites=["a", "a"], models=[MODEL])
    with pytest.raises(ValueError, match="explicit --model"):
        aggregate_receipts(inputs[:2])
    model_b = {"id": "candidate", "revision": "1"}
    with pytest.raises(ValueError, match="same set"):
        aggregate_receipts(
            inputs[:3], sites=["a", "b", "a"], models=[MODEL, MODEL, model_b]
        )
    result = aggregate_receipts(
        inputs, sites=["a", "b", "a", "b"], models=[MODEL, MODEL, model_b, model_b]
    )
    assert len(result["shareable"]["models"]) == 2
    assert result["shareable"]["paired_sites"] == []


def test_public_export_approves_labels_rebuilds_math_and_excludes_private_fields(
    tmp_path,
):
    import jsonschema

    inputs = [receipt(tmp_path, "a"), receipt(tmp_path, "b", mae=0.4)]
    artifact = aggregate_receipts(inputs, models=[MODEL], assume_disjoint_sites=True)
    schema = json.loads(
        Path(
            "privatelabbench/data/schemas/cross-site-aggregate-v1.schema.json"
        ).read_text()
    )
    jsonschema.validate(artifact, schema)
    artifact["shareable"]["models"][0]["summary"]["pooled"]["estimate"] = 123456
    artifact["shareable"]["models"][0]["sites"][0]["private"] = "protected-row-id"
    artifact["shareable"]["private"] = "protected-training-membership"
    decision, public = check_release(artifact, release())
    assert decision.decision == "allow"
    jsonschema.validate(attach_integrity_metadata(public), schema)
    assert public["shareable"]["models"][0]["summary"]["pooled"][
        "estimate"
    ] == pytest.approx(0.3)
    assert "protected" not in json.dumps(
        public
    ) and "input_verification" not in json.dumps(public)
    for policy in (
        release(include_protocol=False),
        release(public_models=[]),
        release(public_sites=["site-1"]),
        release(min_cell_size=21),
    ):
        assert check_release(artifact, policy)[1] is None
    path = tmp_path / "public.json"
    assert publish_shareable_artifact(artifact, release(), path).decision == "allow"
    assert verify_report(str(path))["valid"]
    artifact["shareable"]["models"][0]["sites"][0]["estimate"] = 0.1
    assert (
        publish_shareable_artifact(artifact, release(), path).decision == "needs_review"
    )
    assert not path.exists()


def test_trusted_signatures_required_and_single_snapshot_verification(tmp_path):
    inputs = [receipt(tmp_path, "a"), receipt(tmp_path, "b")]
    with pytest.raises(ValueError, match="trusted_signer_required"):
        aggregate_receipts(inputs, models=[MODEL], require_trusted_signer=True)
    payload = json.loads(inputs[0].read_text())
    assert verify_payload(payload)["valid"]
    snapshot = deepcopy(payload)
    payload["shareable"]["evaluation"]["metrics"]["mae"] += 1
    assert not verify_payload(payload)["valid"]
    assert verify_payload(snapshot)["valid"]


def test_pinned_model_claims_can_supply_identity_without_manual_override(tmp_path):
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )
    from privatelabbench.reports.trust import sign_artifact

    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "private.pem"
    key_path.write_bytes(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    )
    signer = {
        "signer_id": "independent-lab",
        "key_id": "reviewed-key",
        "private_key": str(key_path),
        "model": MODEL,
    }
    inputs = [receipt(tmp_path, "a"), receipt(tmp_path, "b")]
    for path in inputs:
        path.write_text(json.dumps(sign_artifact(json.loads(path.read_text()), signer)))
    trust = {
        "schema_version": "receipt-trust-store/v1",
        "keys": {
            "reviewed-key": {
                "signer_id": "independent-lab",
                "public_key": base64.b64encode(
                    key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                ).decode(),
            }
        },
    }
    result = aggregate_receipts(inputs, trust_store=trust, require_trusted_signer=True)
    assert result["shareable"]["models"][0]["model"] == MODEL
    assert all(row["signer_trusted"] for row in result["local"]["input_verification"])
    with pytest.raises(ValueError, match="conflicts"):
        aggregate_receipts(
            inputs, trust_store=trust, models=[{"id": "wrong-model", "revision": "1"}]
        )


def test_protocol_bound_paired_artifacts_preserve_within_site_evidence(
    tmp_path, monkeypatch, capsys
):
    rules = resolve_protocol("plb://generic/regression@1.0.0").as_dict()
    rules["version"] = "1.0.1"
    rules["comparison"]["resamples"] = 100
    rules["comparison"]["permutations"] = 0
    protocol = tmp_path / "protocol.yaml"
    protocol.write_text(yaml.safe_dump(rules))
    source_policy = tmp_path / "source-release.yaml"
    source_policy.write_text(
        yaml.safe_dump(
            {
                key: value
                for key, value in release().items()
                if key not in {"public_sites", "public_models"}
            }
        )
    )
    inputs = []
    for site in ("alpha", "beta"):
        paths = []
        for model, error in (("a", 0.1), ("b", 0.3)):
            path = tmp_path / f"{site}-{model}.csv"
            path.write_text(
                "sample_id,target,prediction\n"
                + "".join(f"{i},{i},{i+error}\n" for i in range(24))
            )
            paths.append(path)
        output = tmp_path / f"{site}.json"
        monkeypatch.setattr(
            "sys.argv",
            [
                "plb",
                "compare",
                *map(str, paths),
                "--target",
                "target",
                "--protocol",
                str(protocol),
                "--release-policy",
                str(source_policy),
                "--json-report",
                str(output),
                "--report",
                str(output.with_suffix(".md")),
            ],
        )
        assert main() == 0
        public = tmp_path / f"{site}.shareable.json"
        assert public.exists()
        inputs.append(public)
    models = [{"id": "candidate", "revision": "1"}, {"id": "baseline", "revision": "1"}]
    artifact = aggregate_receipts(inputs, models=models)
    assert len(artifact["shareable"]["models"]) == 2
    assert all(
        row["improvement_a_over_b"] == pytest.approx(0.2)
        for row in artifact["shareable"]["paired_sites"]
    )
    assert all(
        row["interval"]["status"] == "evaluated"
        for row in artifact["shareable"]["paired_sites"]
    )
    decision, public = check_release(artifact, release(public_models=models))
    assert (
        decision.decision == "allow" and len(public["shareable"]["paired_sites"]) == 2
    )
    assert "sample_id" not in json.dumps(public) and "private.pem" not in json.dumps(
        public
    )
    # Explicit scientific overrides cannot silently alter the frozen comparison.
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "compare",
            *map(str, paths),
            "--target",
            "target",
            "--protocol",
            str(protocol),
            "--resamples",
            "200",
            "--json-report",
            str(tmp_path / "conflict.json"),
        ],
    )
    with pytest.raises(ValueError, match="conflicts"):
        main()


def test_cli_generates_local_output_gates_public_output_and_cleans_stale_export(
    tmp_path, monkeypatch, capsys
):
    inputs = [receipt(tmp_path, "a"), receipt(tmp_path, "b")]
    output = tmp_path / "aggregate.json"
    public = tmp_path / "aggregate.shareable.json"
    policy = tmp_path / "release.yaml"
    policy.write_text(yaml.safe_dump(release()))
    args = [
        "plb",
        "aggregate",
        *map(str, inputs),
        "--model",
        "published-model@frozen-1",
        "--out",
        str(output),
    ]
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0 and output.exists() and not public.exists()
    monkeypatch.setattr("sys.argv", args + ["--release-policy", str(policy)])
    assert main() == 0 and public.exists() and output.with_suffix(".md").exists()
    payload = json.loads(inputs[1].read_text())
    payload["shareable"]["evaluation"]["metrics"]["mae"] = 123
    inputs[1].write_text(json.dumps(payload))
    assert (
        main() == 2 and not public.exists() and not output.with_suffix(".md").exists()
    )
    assert "failed verification" in capsys.readouterr().out

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from privatelabbench.cli import main
from privatelabbench.config import load_config
from privatelabbench.privacy.export import check_release
from privatelabbench.protocols import EvaluationProtocol, apply_protocol, discover_protocols, resolve_protocol
from privatelabbench.runner import run_config

REF = "plb://generic/regression@1.0.0"


def definition():
    return resolve_protocol(REF).as_dict()


def test_bundled_schemas_and_immutable_canonical_identity():
    root = Path("privatelabbench/data/schemas")
    registry = Registry().with_resources((name, Resource.from_contents(json.loads((root / name).read_text()))) for name in ("release-policy-v1.schema.json", "quality-policy-v1.schema.json"))
    schema = json.loads((root / "evaluation-protocol-v1.schema.json").read_text())
    for protocol in discover_protocols():
        Draft202012Validator(schema, registry=registry).validate(protocol.as_dict())
        rules = protocol.as_dict()
        assert EvaluationProtocol.from_dict(dict(reversed(list(rules.items())))).sha256 == protocol.sha256
        rules["uncertainty"]["seed"] += 1
        assert EvaluationProtocol.from_dict(rules).sha256 != protocol.sha256
        assert protocol.as_dict()["uncertainty"]["seed"] == 13
        assert protocol.comparison_config().metric == protocol.identity()["primary_metric"]


@pytest.mark.parametrize("section,key,value", [
    (None, "task", "molecules"), (None, "primary_metric", "auroc"), (None, "version", "latest"),
    (None, "metrics", ["mae", "auroc"]), (None, "schema_version", "benchmark-pack/v1"),
    ("input_schema", "schema_version", "prediction-table/v2"), ("input_schema", "require_sample_id", "false"),
    ("uncertainty", "resamples", True), ("uncertainty", "confidence_level", float("nan")),
    ("uncertainty", "seed", -1), ("privacy", "epsilon", float("inf")),
    ("release", "enabled", True), ("artifact_versions", "receipt", "evaluation-receipt/v2"),
    ("comparison", "metric", "auroc"), ("slices", "min_size", 1),
])
def test_incompatible_protocols_refused(section, key, value):
    rules = definition()
    (rules if section is None else rules[section])[key] = value
    with pytest.raises(ValueError):
        EvaluationProtocol.from_dict(rules)


def test_plugins_and_conflicting_versions(monkeypatch):
    rules = definition()
    entry = SimpleNamespace(load=lambda: lambda: [rules])
    monkeypatch.setattr("privatelabbench.protocols.metadata.entry_points", lambda: {"privatelabbench.protocols": [entry]})
    assert len([p for p in discover_protocols() if p.ref == REF]) == 1
    rules["uncertainty"]["seed"] = 14
    with pytest.raises(ValueError, match="Conflicting definitions"):
        discover_protocols()
    rules["version"] = "1.0.1"
    assert any(p.ref.endswith("@1.0.1") for p in discover_protocols())


def test_no_floating_versions_or_mutated_run_settings():
    with pytest.raises(ValueError, match="explicit semantic version"):
        resolve_protocol("plb://generic/regression")
    protocol = resolve_protocol(REF)
    for payload in ({"input": {"task_type": "classification"}}, {"uncertainty": {"resamples": 100}}, {"input": {"slice_columns": ["secret-study"]}}, {"release": {"min_samples": 2}}, {"quality_gate": {"schema_version": "quality-policy/v1", "min_samples": 20}}):
        with pytest.raises(ValueError):
            apply_protocol(payload, protocol)
    rules = protocol.as_dict()
    rules["slices"]["required"] = ["site"]
    rules["slices"]["optional"] = ["batch"]
    rules["release"]["require_privacy_audit"] = True
    protocol = EvaluationProtocol.from_dict(rules)
    assert apply_protocol({}, protocol)["input"]["slice_columns"] == ["site"]
    with pytest.raises(ValueError, match="required slices"):
        apply_protocol({"input": {"slice_columns": []}}, protocol)
    with pytest.raises(ValueError, match="cannot weaken"):
        apply_protocol({"release": {"require_privacy_audit": False}}, protocol)


def test_two_private_datasets_share_exact_identity_and_export_requires_consent(tmp_path, monkeypatch, capsys):
    identities = []
    for site, offset in (("alpha", 0.1), ("beta", 0.4)):
        folder = tmp_path / site
        folder.mkdir()
        table = folder / "private.csv"
        table.write_text("sample_id,actual,predicted\n" + "".join(f"{site}-{i},{i},{i+offset}\n" for i in range(24)))
        cfg = {"project": site, "protocol": REF, "input": {"path": str(table), "target_column": "actual", "prediction_column": "predicted"}, "report": {"json": str(folder / "run.json"), "markdown": str(folder / "run.md"), "manifest": str(folder / "run_manifest.json")}, "audit": {"path": str(folder / "audit.jsonl")}}
        path = folder / "local.yaml"
        path.write_text(yaml.safe_dump(cfg))
        if site == "alpha":
            run_config(str(path))
        else:
            monkeypatch.setattr("sys.argv", ["plb", "run", str(path), "--protocol", REF])
            assert main() == 0
            assert REF in capsys.readouterr().out
        local = json.loads((folder / "run_receipt.json").read_text())
        identities.append(local["shareable"]["evaluation"]["protocol"])
        assert local["local"]["protocol_definition"] == definition()
        assert local["shareable"]["evaluation"]["protocol"] == resolve_protocol(REF).identity()
        assert not (folder / "run_receipt.shareable.json").exists()
        release = {**definition()["release"], "enabled": True}
        decision, shared = check_release(local, release, evidence=local["local"]["release_evidence"])
        assert decision.decision == "allow"
        assert "protocol" not in shared["shareable"]["evaluation"]
        release["include_protocol"] = True
        decision, shared = check_release(local, release, evidence=local["local"]["release_evidence"])
        assert decision.decision == "allow"
        assert shared["shareable"]["evaluation"]["protocol"] == identities[-1]
        public_text = json.dumps(shared)
        assert str(table) not in public_text and "protocol_definition" not in public_text
        assert set(shared["shareable"]["evaluation"]["protocol"]) == {"id", "version", "sha256", "metrics", "primary_metric"}
        tampered = deepcopy(local)
        tampered["shareable"]["evaluation"]["protocol"]["sha256"] = "invalid"
        decision, exported = check_release(tampered, release, evidence=local["local"]["release_evidence"])
        assert decision.decision == "needs_review" and exported is None
    assert identities[0] == identities[1]


def test_config_local_path_resolution_and_cli_commands(tmp_path, monkeypatch, capsys):
    path = tmp_path / "protocol.yaml"
    path.write_text(yaml.safe_dump(definition()))
    config = tmp_path / "local.yaml"
    config.write_text("protocol: protocol.yaml\n")
    assert load_config(str(config)).protocol.sha256 == resolve_protocol(REF).sha256
    other = definition()
    other["version"] = "1.0.1"
    path.write_text(yaml.safe_dump(other))
    with pytest.raises(ValueError, match="conflicts"):
        load_config(str(config), protocol_override=REF)
    monkeypatch.setattr("sys.argv", ["plb", "list-protocols"])
    assert main() == 0 and REF in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["plb", "show-protocol", REF])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["identity"] == resolve_protocol(REF).identity()


def test_binary_protocol_requires_fixed_label_order_and_withdrawn_version_is_rejected(tmp_path):
    from privatelabbench.eval.predictions import evaluate_prediction_csv
    protocol = resolve_protocol("plb://generic/binary@1.0.1")
    assert protocol.as_dict()["input_schema"]["class_labels"] == ["0", "1"]
    rows = [("positive", 1, 0.9), ("negative", 0, 0.1), ("positive-2", 1, 0.8), ("negative-2", 0, 0.2)]
    scores = []
    for index, ordered in enumerate((rows, list(reversed(rows)))):
        path = tmp_path / f"binary-{index}.csv"
        path.write_text("sample_id,target,prediction\n" + "".join(f"{sample},{target},{prediction}\n" for sample, target, prediction in ordered))
        bound = apply_protocol({}, protocol)
        for labels in (None, bound["input"]["class_labels"]):
            result = evaluate_prediction_csv(str(path), target="target", prediction_column="prediction", task_type="classification", class_labels=labels)
            scores.append(result.metrics)
    assert all(score["auroc"] == 1.0 and score["accuracy"] == 1.0 for score in scores)
    rules = protocol.as_dict()
    rules["input_schema"]["class_labels"] = []
    with pytest.raises(ValueError, match="ordered class_labels"):
        EvaluationProtocol.from_dict(rules)
    with pytest.raises(ValueError, match="label order"):
        resolve_protocol("plb://generic/binary@1.0.0")

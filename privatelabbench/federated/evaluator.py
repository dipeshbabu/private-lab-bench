from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from privatelabbench.models.sklearn_baseline import evaluate_random_forest
from privatelabbench.privacy.aggregation import aggregate_client_metrics
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics
from privatelabbench.tasks.molecules import load_molecule_csv


@dataclass(frozen=True)
class ClientEvaluation:
    client_id: str
    dataset_path: str
    n_samples: int
    n_train: int
    n_test: int
    task_type: str
    model: str
    clean_metrics: dict[str, float]
    reported_metrics: dict[str, float]
    shift: dict[str, float]


def discover_client_csvs(directory: str) -> list[Path]:
    root = Path(directory)
    if not root.exists():
        raise FileNotFoundError(f"Client directory does not exist: {directory}")
    if not root.is_dir():
        raise NotADirectoryError(f"Expected a directory of client CSV files: {directory}")
    files = sorted(p for p in root.glob("*.csv") if p.is_file())
    if not files:
        raise ValueError(f"No client CSV files found in {directory}")
    return files


def evaluate_client_csv(
    csv_path: Path,
    *,
    target: str,
    smiles_column: str = "smiles",
    task_type: str | None = None,
    test_size: float = 0.25,
    seed: int = 13,
    privacy_config: PrivacyConfig,
) -> ClientEvaluation:
    dataset = load_molecule_csv(str(csv_path), target=target, smiles_column=smiles_column, task_type=task_type)
    result = evaluate_random_forest(dataset, test_size=test_size, seed=seed)
    clean_metrics = dict(result["metrics"])
    reported_metrics = privatize_metrics(clean_metrics, privacy_config)
    return ClientEvaluation(
        client_id=csv_path.stem,
        dataset_path=str(csv_path),
        n_samples=int(result["n_samples"]),
        n_train=int(result["n_train"]),
        n_test=int(result["n_test"]),
        task_type=str(result["task_type"]),
        model=str(result["model"]),
        clean_metrics=clean_metrics,
        reported_metrics=reported_metrics,
        shift={k: float(v) for k, v in dict(result["shift"]).items()},
    )


def evaluate_federated_directory(
    directory: str,
    *,
    target: str,
    smiles_column: str = "smiles",
    task_type: str | None = None,
    test_size: float = 0.25,
    seed: int = 13,
    privacy_config: PrivacyConfig,
) -> dict[str, object]:
    files = discover_client_csvs(directory)
    clients = [
        evaluate_client_csv(
            path,
            target=target,
            smiles_column=smiles_column,
            task_type=task_type,
            test_size=test_size,
            seed=seed,
            privacy_config=privacy_config,
        )
        for path in files
    ]
    weights = [client.n_samples for client in clients]
    aggregate_clean = aggregate_client_metrics([client.clean_metrics for client in clients], weights=weights)
    aggregate_reported = aggregate_client_metrics([client.reported_metrics for client in clients], weights=weights)
    aggregate_shift = aggregate_client_metrics([client.shift for client in clients], weights=weights)

    task_types = sorted({client.task_type for client in clients})
    models = sorted({client.model for client in clients})
    return {
        "directory": directory,
        "target": target,
        "n_clients": len(clients),
        "total_samples": int(sum(weights)),
        "task_types": task_types,
        "models": models,
        "clients": clients,
        "aggregate_clean_metrics": aggregate_clean,
        "aggregate_reported_metrics": aggregate_reported,
        "aggregate_shift": aggregate_shift,
    }

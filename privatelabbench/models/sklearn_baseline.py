from __future__ import annotations

from privatelabbench.adapters.sklearn_adapter import RandomForestMoleculeAdapter
from privatelabbench.tasks.molecules import MoleculeDataset


def evaluate_random_forest(dataset: MoleculeDataset, test_size: float = 0.25, seed: int = 13) -> dict[str, object]:
    """Backward-compatible wrapper around the adapter-based Random Forest evaluator."""
    return RandomForestMoleculeAdapter().evaluate(dataset, test_size=test_size, seed=seed)

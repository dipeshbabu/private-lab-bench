from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split

from privatelabbench.eval.metrics import classification_metrics, regression_metrics
from privatelabbench.eval.shift import feature_shift_summary
from privatelabbench.tasks.molecules import MoleculeDataset, hashed_smiles_fingerprints


def evaluate_random_forest(dataset: MoleculeDataset, test_size: float = 0.25, seed: int = 13) -> dict[str, object]:
    x = hashed_smiles_fingerprints(dataset.smiles)
    stratify = dataset.y if dataset.task_type == "classification" and len(set(dataset.y.tolist())) > 1 else None
    x_train, x_test, y_train, y_test = train_test_split(
        x, dataset.y, test_size=test_size, random_state=seed, stratify=stratify
    )

    if dataset.task_type == "classification":
        model = RandomForestClassifier(n_estimators=200, random_state=seed, class_weight="balanced")
        model.fit(x_train, y_train.astype(int))
        if hasattr(model, "predict_proba"):
            y_score = model.predict_proba(x_test)[:, 1]
        else:
            y_score = model.predict(x_test)
        metrics = classification_metrics(y_test.astype(int), y_score)
    else:
        model = RandomForestRegressor(n_estimators=200, random_state=seed)
        model.fit(x_train, y_train)
        y_pred = model.predict(x_test)
        metrics = regression_metrics(y_test, y_pred)

    return {
        "model": model.__class__.__name__,
        "task_type": dataset.task_type,
        "n_samples": dataset.n_samples,
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
        "metrics": metrics,
        "shift": feature_shift_summary(x_train, x_test),
    }

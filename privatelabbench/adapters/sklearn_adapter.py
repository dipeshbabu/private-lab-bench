from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split

from privatelabbench.adapters.fingerprints import build_fingerprint_adapter
from privatelabbench.eval.metrics import classification_metrics, regression_metrics
from privatelabbench.eval.shift import feature_shift_summary
from privatelabbench.eval.slices import classification_error_slices, regression_error_slices
from privatelabbench.privacy.attacks import membership_inference_risk
from privatelabbench.tasks.molecules import MoleculeDataset


@dataclass
class RandomForestMoleculeAdapter:
    fingerprint: str = "hashed"
    n_bits: int = 256
    radius: int = 2
    n_estimators: int = 200

    @property
    def name(self) -> str:
        return f"random_forest_{self.fingerprint}"

    def evaluate(self, dataset: MoleculeDataset, *, test_size: float = 0.25, seed: int = 13) -> dict[str, object]:
        featurizer = build_fingerprint_adapter(self.fingerprint, n_bits=self.n_bits, radius=self.radius)
        x = featurizer.transform(dataset.smiles)
        stratify = dataset.y if dataset.task_type == "classification" and len(set(dataset.y.tolist())) > 1 else None
        x_train, x_test, y_train, y_test = train_test_split(
            x, dataset.y, test_size=test_size, random_state=seed, stratify=stratify
        )

        if dataset.task_type == "classification":
            model = RandomForestClassifier(
                n_estimators=self.n_estimators,
                random_state=seed,
                class_weight="balanced",
            )
            model.fit(x_train, y_train.astype(int))
            if hasattr(model, "predict_proba"):
                y_train_score = model.predict_proba(x_train)[:, 1]
                y_score = model.predict_proba(x_test)[:, 1]
            else:
                y_train_score = model.predict(x_train)
                y_score = model.predict(x_test)
            metrics = classification_metrics(y_test.astype(int), y_score)
            slices = classification_error_slices(y_test.astype(int), y_score)
        else:
            model = RandomForestRegressor(n_estimators=self.n_estimators, random_state=seed)
            model.fit(x_train, y_train)
            y_train_score = model.predict(x_train)
            y_score = model.predict(x_test)
            metrics = regression_metrics(y_test, y_score)
            slices = regression_error_slices(y_test, y_score)

        privacy_risk = membership_inference_risk(
            train_y=y_train,
            train_score=y_train_score,
            test_y=y_test,
            test_score=y_score,
            task_type=dataset.task_type,
        )

        return {
            "model": model.__class__.__name__,
            "adapter": self.name,
            "fingerprint": featurizer.name,
            "task_type": dataset.task_type,
            "n_samples": dataset.n_samples,
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
            "metrics": metrics,
            "shift": feature_shift_summary(x_train, x_test),
            "error_slices": slices,
            "privacy_risk": privacy_risk,
        }


def build_molecule_adapter(model_config: dict[str, object] | None = None) -> RandomForestMoleculeAdapter:
    model_config = model_config or {}
    adapter = str(model_config.get("adapter", "hashed_random_forest")).strip().lower().replace("-", "_")
    fingerprint = str(model_config.get("fingerprint", "hashed"))
    if adapter in {"hashed_random_forest", "random_forest", "sklearn_random_forest"}:
        fingerprint = str(model_config.get("fingerprint", "hashed"))
    elif adapter in {"rdkit_random_forest", "morgan_random_forest"}:
        fingerprint = str(model_config.get("fingerprint", "rdkit_morgan"))
    else:
        raise ValueError(f"Unsupported molecule model adapter: {adapter}")
    return RandomForestMoleculeAdapter(
        fingerprint=fingerprint,
        n_bits=int(model_config.get("n_bits", 256 if fingerprint == "hashed" else 2048)),
        radius=int(model_config.get("radius", 2)),
        n_estimators=int(model_config.get("n_estimators", 200)),
    )

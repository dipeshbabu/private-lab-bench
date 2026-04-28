from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

_SMILES_CHARS = re.compile(r"[A-Za-z0-9@+\-\[\]\(\)=#$\\/%.]+")


@dataclass(frozen=True)
class MoleculeDataset:
    smiles: list[str]
    y: np.ndarray
    task_type: str
    target_column: str

    @property
    def n_samples(self) -> int:
        return len(self.smiles)


def infer_task_type(values: Iterable[float]) -> str:
    unique = sorted(set(float(v) for v in values))
    if len(unique) <= 2 and all(v in {0.0, 1.0} for v in unique):
        return "classification"
    return "regression"


def load_molecule_csv(path: str, target: str, smiles_column: str = "smiles", task_type: str | None = None) -> MoleculeDataset:
    df = pd.read_csv(path)
    required = {smiles_column, target}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(sorted(missing))}")

    df = df[[smiles_column, target]].dropna()
    smiles = df[smiles_column].astype(str).tolist()
    if not smiles:
        raise ValueError("No valid molecule rows found after dropping missing values.")
    invalid = [s for s in smiles if not _SMILES_CHARS.fullmatch(s)]
    if invalid:
        raise ValueError(f"Found invalid SMILES-like values, e.g. {invalid[0]!r}")

    y = df[target].astype(float).to_numpy()
    inferred = task_type or infer_task_type(y)
    if inferred not in {"regression", "classification"}:
        raise ValueError("task_type must be 'regression' or 'classification'")
    return MoleculeDataset(smiles=smiles, y=y, task_type=inferred, target_column=target)


def hashed_smiles_fingerprints(smiles: list[str], n_bits: int = 256, ngram_min: int = 1, ngram_max: int = 4) -> np.ndarray:
    """Stable hashed character n-gram baseline for SMILES-like strings."""
    if n_bits <= 0:
        raise ValueError("n_bits must be positive")
    x = np.zeros((len(smiles), n_bits), dtype=np.float32)
    for row, smi in enumerate(smiles):
        tokens: list[str] = []
        for n in range(ngram_min, ngram_max + 1):
            tokens.extend(smi[i : i + n] for i in range(max(len(smi) - n + 1, 0)))
        for token in tokens or [smi]:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % n_bits
            x[row, idx] += 1.0
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return x / norms

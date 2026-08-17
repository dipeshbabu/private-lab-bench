from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from privatelabbench.core.interfaces import ModelAdapter


class FingerprintAdapter(Protocol):
    """Converts molecule strings into model-ready feature arrays."""

    name: str

    def transform(self, smiles: list[str]) -> np.ndarray:
        """Return a 2D feature matrix for a list of SMILES strings."""


@dataclass(frozen=True)
class AdapterSpec:
    adapter: str = "hashed_random_forest"
    fingerprint: str = "hashed"
    n_bits: int = 256
    radius: int = 2
    n_estimators: int = 200

    @classmethod
    def from_config(cls, data: dict[str, object] | None) -> "AdapterSpec":
        if not data:
            return cls()
        return cls(
            adapter=str(data.get("adapter", "hashed_random_forest")),
            fingerprint=str(data.get("fingerprint", data.get("featurizer", "hashed"))),
            n_bits=int(data.get("n_bits", 256)),
            radius=int(data.get("radius", 2)),
            n_estimators=int(data.get("n_estimators", 200)),
        )


__all__ = ["FingerprintAdapter", "ModelAdapter", "AdapterSpec"]

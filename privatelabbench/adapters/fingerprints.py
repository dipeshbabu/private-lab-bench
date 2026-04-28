from __future__ import annotations

import numpy as np

from privatelabbench.tasks.molecules import hashed_smiles_fingerprints


class HashedSmilesFingerprintAdapter:
    name = "hashed_smiles"

    def __init__(self, n_bits: int = 256) -> None:
        self.n_bits = n_bits

    def transform(self, smiles: list[str]) -> np.ndarray:
        return hashed_smiles_fingerprints(smiles, n_bits=self.n_bits)


class RDKitMorganFingerprintAdapter:
    name = "rdkit_morgan"

    def __init__(self, radius: int = 2, n_bits: int = 2048) -> None:
        self.radius = radius
        self.n_bits = n_bits

    def transform(self, smiles: list[str]) -> np.ndarray:
        try:
            from rdkit import Chem, DataStructs
            from rdkit.Chem import AllChem
        except ImportError as exc:
            raise ImportError(
                "RDKit support is optional. Install with `pip install private-lab-bench[rdkit]` "
                "or install rdkit in the active environment."
            ) from exc

        rows: list[np.ndarray] = []
        for smi in smiles:
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                raise ValueError(f"RDKit could not parse SMILES value: {smi!r}")
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, self.radius, nBits=self.n_bits)
            arr = np.zeros((self.n_bits,), dtype=np.float32)
            DataStructs.ConvertToNumpyArray(fp, arr)
            rows.append(arr)
        if not rows:
            return np.zeros((0, self.n_bits), dtype=np.float32)
        return np.vstack(rows).astype(np.float32)


def build_fingerprint_adapter(name: str, *, n_bits: int = 256, radius: int = 2):
    normalized = name.strip().lower().replace("-", "_")
    if normalized in {"hashed", "hashed_smiles", "hash"}:
        return HashedSmilesFingerprintAdapter(n_bits=n_bits)
    if normalized in {"rdkit", "morgan", "rdkit_morgan"}:
        return RDKitMorganFingerprintAdapter(radius=radius, n_bits=n_bits)
    raise ValueError(f"Unsupported fingerprint adapter: {name}")

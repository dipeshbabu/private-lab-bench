import tenseal as ts
import torch
import numpy as np
from typing import Tuple, Any


class HomomorphicEncryption:
    def __init__(self, context_params: dict = None):
        if context_params is None:
            context_params = {
                "scheme": "ckks",
                "poly_modulus_degree": 8192,
                "coeff_mod_bit_sizes": [60, 40, 40, 60],
            }
        self.context = self._create_context(context_params)

    def _create_context(self, params: dict) -> ts.Context:
        """Create TenSEAL context for homomorphic encryption"""
        context = ts.context(
            ts.SCHEME_TYPE.CKKS,
            poly_modulus_degree=params["poly_modulus_degree"],
            coeff_mod_bit_sizes=params["coeff_mod_bit_sizes"],
        )
        context.global_scale = 2**40
        context.generate_galois_keys()
        return context

    def encrypt_tensor(self, tensor: torch.Tensor) -> ts.CKKSTensor:
        """Encrypt a PyTorch tensor"""
        return ts.ckks_tensor(self.context, tensor.flatten().tolist())

    def decrypt_tensor(
        self, encrypted_tensor: ts.CKKSTensor, original_shape: Tuple
    ) -> torch.Tensor:
        """Decrypt a TenSEAL tensor back to PyTorch tensor"""
        decrypted = torch.tensor(encrypted_tensor.decrypt())
        return decrypted.reshape(original_shape)

    def secure_compute(
        self, encrypted_tensor: ts.CKKSTensor, operation: str
    ) -> ts.CKKSTensor:
        """Perform secure computations on encrypted data"""
        if operation == "square":
            return encrypted_tensor * encrypted_tensor
        elif operation == "mean":
            return encrypted_tensor.sum() / len(encrypted_tensor)
        return encrypted_tensor

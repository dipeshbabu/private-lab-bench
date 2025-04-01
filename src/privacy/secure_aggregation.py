import torch
from typing import List, Dict
import numpy as np
from cryptography.fernet import Fernet


class SecureAggregator:
    def __init__(self, num_parties: int):
        self.num_parties = num_parties
        self.key = Fernet.generate_key()
        self.cipher_suite = Fernet(self.key)

    def generate_mask(self, shape: tuple) -> torch.Tensor:
        """Generate random mask for secure aggregation"""
        return torch.randn(shape)

    def mask_tensor(self, tensor: torch.Tensor) -> torch.Tensor:
        """Apply mask to tensor"""
        mask = self.generate_mask(tensor.shape)
        return tensor + mask, mask

    def aggregate_securely(self, tensors: List[torch.Tensor]) -> torch.Tensor:
        """Securely aggregate multiple tensors"""
        masked_tensors = []
        masks = []

        # Mask each tensor
        for tensor in tensors:
            masked_tensor, mask = self.mask_tensor(tensor)
            masked_tensors.append(masked_tensor)
            masks.append(mask)

        # Aggregate masked tensors
        aggregated = torch.stack(masked_tensors).mean(dim=0)

        # Remove masks
        total_mask = torch.stack(masks).mean(dim=0)
        return aggregated - total_mask

    def encrypt_tensor(self, tensor: torch.Tensor) -> bytes:
        """Encrypt tensor for secure transmission"""
        tensor_bytes = tensor.numpy().tobytes()
        return self.cipher_suite.encrypt(tensor_bytes)

    def decrypt_tensor(self, encrypted_tensor: bytes, shape: tuple) -> torch.Tensor:
        """Decrypt tensor after transmission"""
        decrypted_bytes = self.cipher_suite.decrypt(encrypted_tensor)
        array = np.frombuffer(decrypted_bytes, dtype=np.float32)
        return torch.from_numpy(array.reshape(shape))

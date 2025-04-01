import torch
import torch.nn.functional as F
import numpy as np
from typing import Tuple
import cv2


class ImagePrivacy:
    def __init__(self, privacy_level: float = 0.1):
        self.privacy_level = privacy_level

    def apply_nonlinear_transformation(self, image: torch.Tensor) -> torch.Tensor:
        """Apply nonlinear transformation for privacy"""
        # Wavelet-based transformation
        transformed = torch.fft.fft2(image)
        magnitude = torch.abs(transformed)
        phase = torch.angle(transformed)

        # Modify magnitude while preserving phase
        magnitude = magnitude * (1 + self.privacy_level * torch.randn_like(magnitude))

        # Reconstruct image
        real = magnitude * torch.cos(phase)
        imag = magnitude * torch.sin(phase)
        private_image = torch.fft.ifft2(torch.complex(real, imag)).real

        return private_image

    def geometric_deformation(self, image: torch.Tensor) -> torch.Tensor:
        """Apply geometric deformation for privacy"""
        batch_size, channels, height, width = image.shape

        # Create deformation grid
        theta = torch.randn(batch_size, 2, 3) * self.privacy_level
        grid = F.affine_grid(theta, image.size(), align_corners=False)

        # Apply deformation
        deformed = F.grid_sample(image, grid, align_corners=False)
        return deformed

    def adaptive_noise(self, image: torch.Tensor) -> torch.Tensor:
        """Add adaptive noise based on image content"""
        # Calculate local sensitivity
        edges = self._detect_edges(image)
        noise_level = self.privacy_level * (1 - edges)

        # Add calibrated noise
        noise = torch.randn_like(image) * noise_level
        return image + noise

    def _detect_edges(self, image: torch.Tensor) -> torch.Tensor:
        """Detect edges for adaptive privacy"""
        sobel_x = torch.tensor(
            [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=torch.float32
        ).view(1, 1, 3, 3)
        sobel_y = torch.tensor(
            [[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=torch.float32
        ).view(1, 1, 3, 3)

        edges_x = F.conv2d(image, sobel_x.to(image.device), padding=1)
        edges_y = F.conv2d(image, sobel_y.to(image.device), padding=1)
        edges = torch.sqrt(edges_x.pow(2) + edges_y.pow(2))

        return torch.sigmoid(edges)

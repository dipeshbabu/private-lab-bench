import torch
import torch.nn as nn
import torchxrayvision as xrv
from typing import Dict, Tuple
from privacy.homomorphic import HomomorphicEncryption
from privacy.secure_aggregation import SecureAggregator
from privacy.image_privacy import ImagePrivacy


class EnhancedPrivacyXrayModel(nn.Module):
    def __init__(self, device: torch.device, privacy_config: Dict):
        super().__init__()
        self.device = device
        self.model = xrv.models.DenseNet(weights="densenet121-res224-all")
        self.model = self.model.to(device)

        # Initialize privacy components
        self.homomorphic = HomomorphicEncryption()
        self.secure_aggregator = SecureAggregator(num_parties=1)
        self.image_privacy = ImagePrivacy(
            privacy_level=privacy_config.get("privacy_level", 0.1)
        )

        self.convert_batchnorm_to_groupnorm()

    def convert_batchnorm_to_groupnorm(self):
        """Convert BatchNorm layers to GroupNorm for privacy"""
        for name, module in self.model.named_modules():
            if isinstance(module, nn.BatchNorm2d):
                num_channels = module.num_features
                group_norm = nn.GroupNorm(
                    num_groups=min(32, num_channels), num_channels=num_channels
                ).to(self.device)

                # Copy BatchNorm stats to GroupNorm
                group_norm.weight.data = module.weight.data
                group_norm.bias.data = module.bias.data

                # Set the new module directly
                parent_module = self.model
                name_parts = name.split(".")
                for part in name_parts[:-1]:
                    parent_module = getattr(parent_module, part)
                setattr(parent_module, name_parts[-1], group_norm)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, Dict]:
        # Apply image privacy
        x = self.image_privacy.adaptive_noise(x)
        x = self.image_privacy.geometric_deformation(x)

        # Get features using the model's forward method
        features = self.model.features(x)

        # Encrypt features
        encrypted_features = self.homomorphic.encrypt_tensor(features)

        # Secure computation on encrypted features
        secure_features = self.homomorphic.secure_compute(encrypted_features, "square")

        # Decrypt and reshape
        private_features = self.homomorphic.decrypt_tensor(
            secure_features, features.shape
        )

        # Secure aggregation
        private_features = self.secure_aggregator.aggregate_securely([private_features])

        # Final classification using the model's classifier
        logits = self.model.classifier(
            private_features.view(private_features.size(0), -1)
        )

        return logits, {
            "privacy_metrics": {
                "homomorphic_used": True,
                "secure_aggregation_used": True,
                "image_privacy_level": self.image_privacy.privacy_level,
            }
        }

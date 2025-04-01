import torch
import numpy as np
from lime import lime_image
from skimage.segmentation import mark_boundaries
import matplotlib.pyplot as plt
import cv2
from typing import Dict, List, Tuple


class PrivacyAwareExplainer:
    def __init__(
        self, model: torch.nn.Module, device: torch.device, privacy_budget: float = 1.0
    ):
        self.model = model
        self.device = device
        self.privacy_budget = privacy_budget
        self.explainer = lime_image.LimeImageExplainer()

    def add_noise_to_explanation(self, explanation: np.ndarray) -> np.ndarray:
        """Add calibrated noise to explanation for privacy"""
        sensitivity = np.max(np.abs(explanation))
        noise_scale = sensitivity * np.sqrt(2 * np.log(1.25) / self.privacy_budget)
        noise = np.random.normal(0, noise_scale, explanation.shape)
        return explanation + noise

    def predict_fn(self, images: np.ndarray) -> np.ndarray:
        """Privacy-aware prediction function for LIME"""
        batch = torch.FloatTensor(images).to(self.device)
        if len(batch.shape) == 3:
            batch = batch.unsqueeze(0)
        if batch.shape[1] == 3:
            batch = batch.permute(0, 3, 1, 2)

        with torch.no_grad():
            predictions, _ = self.model(batch)
            probs = torch.sigmoid(predictions)
        return probs.cpu().numpy()

    def generate_lime_explanation(
        self, image: np.ndarray, num_samples: int = 1000
    ) -> Dict:
        """Generate privacy-aware LIME explanation"""
        explanation = self.explainer.explain_instance(
            image, self.predict_fn, top_labels=3, hide_color=0, num_samples=num_samples
        )

        # Get explanation image and mask
        temp, mask = explanation.get_image_and_mask(
            explanation.top_labels[0],
            positive_only=True,
            num_features=5,
            hide_rest=True,
        )

        # Add privacy-preserving noise to mask
        private_mask = self.add_noise_to_explanation(mask)

        return {
            "explanation": explanation,
            "visualization": mark_boundaries(temp, private_mask),
            "importance_map": private_mask,
            "top_labels": explanation.top_labels,
        }

    def generate_saliency_map(self, image: torch.Tensor) -> np.ndarray:
        """Generate privacy-aware saliency map"""
        image.requires_grad_()
        outputs, _ = self.model(image)
        outputs.backward(torch.ones_like(outputs))

        # Get gradients and apply privacy
        saliency = image.grad.abs()
        saliency = torch.mean(saliency, dim=1)

        # Add privacy-preserving noise
        saliency_np = saliency.detach().cpu().numpy()
        private_saliency = self.add_noise_to_explanation(saliency_np)

        return private_saliency

    def visualize_results(
        self,
        image: np.ndarray,
        lime_result: Dict,
        saliency_map: np.ndarray,
        predictions: Dict[str, float],
    ) -> None:
        """Visualize all explanations with privacy considerations"""
        plt.figure(figsize=(15, 5))

        # Original image
        plt.subplot(131)
        plt.imshow(image, cmap="gray")
        plt.title("Original Image")
        plt.axis("off")

        # LIME explanation
        plt.subplot(132)
        plt.imshow(lime_result["visualization"])
        plt.title("Privacy-Aware LIME Explanation")
        plt.axis("off")

        # Saliency map
        plt.subplot(133)
        plt.imshow(saliency_map[0], cmap="hot")
        plt.title("Privacy-Aware Saliency Map")
        plt.axis("off")

        # Add predictions text
        plt.figtext(
            0.02,
            0.02,
            "Top Predictions:\n"
            + "\n".join([f"{k}: {v:.3f}" for k, v in predictions.items() if v > 0.5]),
            fontsize=10,
            bbox=dict(facecolor="white", alpha=0.8),
        )

        plt.tight_layout()
        plt.show()

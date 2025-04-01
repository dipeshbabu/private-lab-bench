import torch
import numpy as np
from sklearn.metrics import (
    roc_auc_score,
    precision_recall_curve,
    average_precision_score,
)
from typing import Dict, List
import json


class PerformanceEvaluator:
    def __init__(self, model, privacy_config):
        self.model = model
        self.privacy_config = privacy_config
        self.results = {
            "auc_roc": [],
            "privacy_metrics": [],
            "explanation_fidelity": [],
            "attack_prevention": [],
        }

    def evaluate_model_performance(self, dataloader):
        """Evaluate model performance metrics"""
        all_preds = []
        all_labels = []

        for images, labels in dataloader:
            with torch.no_grad():
                predictions, _ = self.model(images)
                all_preds.append(torch.sigmoid(predictions))
                all_labels.append(labels)

        all_preds = torch.cat(all_preds).cpu().numpy()
        all_labels = torch.cat(all_labels).cpu().numpy()

        # Calculate AUC-ROC
        auc_roc = roc_auc_score(all_labels, all_preds, average="weighted")
        self.results["auc_roc"].append(auc_roc)

        return auc_roc

    def evaluate_privacy_protection(self, attack_model, test_data):
        """Evaluate privacy protection against attacks"""
        attack_success = []

        for images, _ in test_data:
            # Attempt privacy attack
            attack_result = attack_model.attack(images)
            attack_success.append(attack_result)

        prevention_rate = 1 - np.mean(attack_success)
        self.results["attack_prevention"].append(prevention_rate)

        return prevention_rate

    def evaluate_explanation_fidelity(self, explainer, test_data):
        """Evaluate explanation fidelity"""
        fidelity_scores = []

        for images, labels in test_data:
            # Generate explanations
            explanations = explainer.generate_explanation(images)

            # Calculate fidelity
            fidelity = self._calculate_explanation_fidelity(
                explanations, images, labels
            )
            fidelity_scores.append(fidelity)

        avg_fidelity = np.mean(fidelity_scores)
        self.results["explanation_fidelity"].append(avg_fidelity)

        return avg_fidelity

    def _calculate_explanation_fidelity(self, explanations, images, labels):
        """Calculate explanation fidelity score"""
        original_pred = self.model(images)[0]
        masked_images = images * explanations["importance_map"]
        masked_pred = self.model(masked_images)[0]

        return float(torch.mean(torch.abs(original_pred - masked_pred)).item())

    def save_results(self, output_path):
        """Save evaluation results"""
        with open(output_path, "w") as f:
            json.dump(self.results, f, indent=4)

from __future__ import annotations

from dataclasses import dataclass

from privatelabbench.eval.predictions import evaluate_prediction_csv


@dataclass(frozen=True)
class ExternalPredictionAdapter:
    """Adapter for customer-owned predictions generated outside PrivateLabBench."""

    target_column: str
    prediction_column: str
    task_type: str | None = None
    split_column: str | None = None
    name: str = "external_predictions"

    def evaluate_csv(self, csv_path: str):
        return evaluate_prediction_csv(
            csv_path,
            target=self.target_column,
            prediction_column=self.prediction_column,
            task_type=self.task_type,
            split_column=self.split_column,
        )

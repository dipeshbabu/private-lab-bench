from __future__ import annotations

import math
from collections.abc import Iterable, Mapping


def aggregate_client_metrics(
    client_metrics: Iterable[Mapping[str, float]],
    weights: Iterable[float] | None = None,
) -> dict[str, float]:
    """Average available client metrics; zero-weight clients contribute no evidence.

    This descriptive mean does not reconstruct pooled nonlinear metrics.
    """
    metrics = list(client_metrics)
    if not metrics:
        raise ValueError("client_metrics must contain at least one client")
    if weights is None:
        weights_list = [1.0] * len(metrics)
    else:
        weights_list = [float(w) for w in weights]
    if len(weights_list) != len(metrics):
        raise ValueError("weights must match number of client metric dictionaries")
    if any(not math.isfinite(weight) or weight < 0 for weight in weights_list):
        raise ValueError("weights must be finite and nonnegative")
    clients = [
        (metric, weight) for metric, weight in zip(metrics, weights_list) if weight > 0
    ]
    if not clients:
        raise ValueError("weights must contain at least one positive value")

    keys = set().union(*(metric.keys() for metric, weight in clients))
    output: dict[str, float] = {}
    for key in keys:
        available = [
            (float(metric[key]), weight) for metric, weight in clients if key in metric
        ]
        # Scale and normalize per metric: missing values must not dilute its mean,
        # and large but finite weights must not overflow their sum or products.
        scale = max(weight for value, weight in available)
        denominator = math.fsum(weight / scale for value, weight in available)
        output[key] = math.fsum(
            (weight / scale / denominator) * value for value, weight in available
        )
    return output

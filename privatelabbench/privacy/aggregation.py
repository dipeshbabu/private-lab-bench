from __future__ import annotations

from collections.abc import Iterable, Mapping


def aggregate_client_metrics(client_metrics: Iterable[Mapping[str, float]], weights: Iterable[float] | None = None) -> dict[str, float]:
    metrics = list(client_metrics)
    if not metrics:
        raise ValueError("client_metrics must contain at least one client")
    if weights is None:
        weights_list = [1.0] * len(metrics)
    else:
        weights_list = [float(w) for w in weights]
    if len(weights_list) != len(metrics):
        raise ValueError("weights must match number of client metric dictionaries")
    total = sum(weights_list)
    if total <= 0:
        raise ValueError("sum of weights must be positive")

    keys = set().union(*(m.keys() for m in metrics))
    output: dict[str, float] = {}
    for key in keys:
        numerator = 0.0
        denominator = 0.0
        for metric, weight in zip(metrics, weights_list):
            if key in metric:
                numerator += float(metric[key]) * weight
                denominator += weight
        output[key] = numerator / denominator
    return output

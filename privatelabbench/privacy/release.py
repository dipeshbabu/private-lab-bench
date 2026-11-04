from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AggregateReleasePolicy:
    min_clients: int = 1
    min_total_samples: int | None = None
    min_client_samples: int | None = None

    def __post_init__(self) -> None:
        for name in ("min_clients", "min_total_samples", "min_client_samples"):
            value = getattr(self, name)
            if value is None and name != "min_clients":
                continue
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
                raise ValueError(
                    f"privacy.aggregate_policy.{name} must be a positive integer."
                )

    @classmethod
    def from_config(cls, value: Mapping[str, Any] | None) -> "AggregateReleasePolicy":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("privacy.aggregate_policy must be a mapping.")
        if set(value) - {"min_clients", "min_total_samples", "min_client_samples"}:
            raise ValueError("Unknown privacy.aggregate_policy fields.")
        return cls(**value)


def evaluate_aggregate_release(
    *,
    n_clients: int,
    total_samples: int,
    client_sample_counts: Sequence[int],
    policy: AggregateReleasePolicy | None = None,
) -> dict[str, Any]:
    policy = policy or AggregateReleasePolicy()
    violations: list[str] = []
    counts = list(client_sample_counts)
    if any(
        isinstance(value, bool) or not isinstance(value, Integral) or value < 0
        for value in [n_clients, total_samples, *counts]
    ):
        raise ValueError("Aggregate evidence requires nonnegative integer counts.")
    if n_clients != len(counts) or total_samples != sum(counts):
        raise ValueError("Aggregate evidence counts must match the supplied clients.")
    if n_clients < policy.min_clients:
        violations.append("min_clients_not_met")
    if (
        policy.min_total_samples is not None
        and total_samples < policy.min_total_samples
    ):
        violations.append("min_total_samples_not_met")
    if policy.min_client_samples is not None:
        small_clients = sum(1 for count in counts if count < policy.min_client_samples)
        if small_clients:
            violations.append("min_client_samples_not_met")

    return {
        "status": "fail" if violations else "pass",
        "publishable": not violations,
        "policy": {
            "min_clients": policy.min_clients,
            "min_total_samples": policy.min_total_samples,
            "min_client_samples": policy.min_client_samples,
        },
        "observed": {
            "n_clients": n_clients,
            "total_samples": total_samples,
            "min_client_samples": min(counts) if counts else 0,
        },
        "violations": violations,
    }

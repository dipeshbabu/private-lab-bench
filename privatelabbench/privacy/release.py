from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AggregateReleasePolicy:
    min_clients: int = 1
    min_total_samples: int | None = None
    min_client_samples: int | None = None

    @classmethod
    def from_config(cls, value: Mapping[str, Any] | None) -> "AggregateReleasePolicy":
        if not value:
            return cls()
        return cls(
            min_clients=int(value.get("min_clients", 1)),
            min_total_samples=(
                int(value["min_total_samples"]) if value.get("min_total_samples") is not None else None
            ),
            min_client_samples=(
                int(value["min_client_samples"]) if value.get("min_client_samples") is not None else None
            ),
        )


def evaluate_aggregate_release(
    *,
    n_clients: int,
    total_samples: int,
    client_sample_counts: Sequence[int],
    policy: AggregateReleasePolicy | None = None,
) -> dict[str, Any]:
    policy = policy or AggregateReleasePolicy()
    violations: list[str] = []
    if policy.min_clients < 1:
        raise ValueError("privacy.aggregate_policy.min_clients must be at least 1.")
    if n_clients < policy.min_clients:
        violations.append("min_clients_not_met")
    if policy.min_total_samples is not None and total_samples < policy.min_total_samples:
        violations.append("min_total_samples_not_met")
    if policy.min_client_samples is not None:
        small_clients = sum(1 for count in client_sample_counts if count < policy.min_client_samples)
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
            "min_client_samples": min(client_sample_counts) if client_sample_counts else 0,
        },
        "violations": violations,
    }

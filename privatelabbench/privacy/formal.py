from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np


ADJACENCY_MODEL = "fixed_size_replace_one"


@dataclass(frozen=True)
class BoundedMeanQuery:
    """A bounded mean query with analytically established L1 sensitivity.

    The guarantee assumes a fixed-size dataset and replace-one adjacency: adjacent
    datasets have equal size and differ in one individual's bounded value.
    Values are clipped locally to [lower, upper] before aggregation.
    """

    name: str
    values: Sequence[float]
    lower: float
    upper: float

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("query name must not be empty")
        if not np.isfinite(self.lower) or not np.isfinite(self.upper):
            raise ValueError("query bounds must be finite")
        if self.lower >= self.upper:
            raise ValueError("query lower bound must be smaller than upper bound")
        if len(self.values) == 0:
            raise ValueError("bounded mean query requires at least one value")
        values = np.asarray(self.values, dtype=float)
        if not np.all(np.isfinite(values)):
            raise ValueError("bounded mean query values must be finite before clipping")

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def sensitivity(self) -> float:
        self.validate()
        return float((self.upper - self.lower) / self.n)

    def clipped_mean(self) -> float:
        self.validate()
        values = np.asarray(self.values, dtype=float)
        return float(np.mean(np.clip(values, self.lower, self.upper)))


@dataclass(frozen=True)
class PrivacySpend:
    label: str
    epsilon: float
    delta: float = 0.0


@dataclass
class PrivacyBudget:
    """Simple sequential-composition ledger for pure/approximate DP spends."""

    epsilon_limit: float
    delta_limit: float = 0.0
    spends: list[PrivacySpend] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.epsilon_limit <= 0:
            raise ValueError("epsilon_limit must be positive")
        if self.delta_limit < 0 or self.delta_limit >= 1:
            raise ValueError("delta_limit must satisfy 0 <= delta < 1")

    @property
    def epsilon_spent(self) -> float:
        return float(sum(spend.epsilon for spend in self.spends))

    @property
    def delta_spent(self) -> float:
        return float(sum(spend.delta for spend in self.spends))

    @property
    def epsilon_remaining(self) -> float:
        return float(self.epsilon_limit - self.epsilon_spent)

    @property
    def delta_remaining(self) -> float:
        return float(self.delta_limit - self.delta_spent)

    def spend(self, *, label: str, epsilon: float, delta: float = 0.0) -> None:
        if epsilon <= 0:
            raise ValueError("epsilon spend must be positive")
        if delta < 0 or delta >= 1:
            raise ValueError("delta spend must satisfy 0 <= delta < 1")
        if self.epsilon_spent + epsilon > self.epsilon_limit + 1e-12:
            raise ValueError("privacy epsilon budget exceeded")
        if self.delta_spent + delta > self.delta_limit + 1e-18:
            raise ValueError("privacy delta budget exceeded")
        self.spends.append(PrivacySpend(label=label, epsilon=float(epsilon), delta=float(delta)))

    def as_dict(self) -> dict[str, object]:
        return {
            "composition": "sequential_sum",
            "epsilon_limit": self.epsilon_limit,
            "epsilon_spent": self.epsilon_spent,
            "epsilon_remaining": self.epsilon_remaining,
            "delta_limit": self.delta_limit,
            "delta_spent": self.delta_spent,
            "delta_remaining": self.delta_remaining,
            "spends": [spend.__dict__ for spend in self.spends],
        }


@dataclass(frozen=True)
class BoundedMeanRelease:
    name: str
    value: float
    clipped_mean: float
    lower: float
    upper: float
    n: int
    sensitivity: float
    epsilon: float
    delta: float
    noise_scale: float
    adjacency: str = ADJACENCY_MODEL
    guarantee: str = "pure_epsilon_dp_mathematical_model"

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def release_bounded_mean(
    query: BoundedMeanQuery,
    *,
    epsilon: float,
    seed: int | None = None,
    budget: PrivacyBudget | None = None,
) -> BoundedMeanRelease:
    """Release one bounded mean with the Laplace mechanism.

    Under fixed-size replace-one adjacency, clipping to [lower, upper] gives
    sensitivity (upper-lower)/n. Adding Laplace noise with scale sensitivity/epsilon
    yields pure epsilon-DP in the mathematical real-arithmetic model.

    This reference implementation uses NumPy floating-point sampling. For
    high-assurance deployments where implementation-level numerical details must be
    covered by the privacy proof, use a vetted DP library/backend such as OpenDP.
    """

    query.validate()
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    if budget is not None:
        budget.spend(label=query.name, epsilon=epsilon, delta=0.0)
    sensitivity = query.sensitivity
    scale = sensitivity / epsilon
    rng = np.random.default_rng(seed)
    center = query.clipped_mean()
    value = float(center + rng.laplace(0.0, scale))
    return BoundedMeanRelease(
        name=query.name,
        value=value,
        clipped_mean=center,
        lower=float(query.lower),
        upper=float(query.upper),
        n=query.n,
        sensitivity=sensitivity,
        epsilon=float(epsilon),
        delta=0.0,
        noise_scale=float(scale),
    )


def release_bounded_means(
    queries: Iterable[BoundedMeanQuery],
    *,
    epsilon_total: float,
    seed: int | None = None,
    weights: Sequence[float] | None = None,
) -> dict[str, object]:
    """Release multiple bounded means with explicit sequential composition.

    `epsilon_total` is allocated equally unless positive `weights` are supplied.
    The ledger rejects releases that exceed the declared total budget.
    """

    query_list = list(queries)
    if not query_list:
        raise ValueError("at least one bounded mean query is required")
    if epsilon_total <= 0:
        raise ValueError("epsilon_total must be positive")
    if len({query.name for query in query_list}) != len(query_list):
        raise ValueError("bounded mean query names must be unique")

    if weights is None:
        allocations = [epsilon_total / len(query_list)] * len(query_list)
    else:
        if len(weights) != len(query_list):
            raise ValueError("weights must contain one value per query")
        if any(weight <= 0 for weight in weights):
            raise ValueError("weights must all be positive")
        total_weight = float(sum(weights))
        allocations = [epsilon_total * float(weight) / total_weight for weight in weights]

    budget = PrivacyBudget(epsilon_limit=float(epsilon_total), delta_limit=0.0)
    seed_sequence = np.random.SeedSequence(seed)
    child_seeds = seed_sequence.spawn(len(query_list))
    releases: list[BoundedMeanRelease] = []
    for query, epsilon, child_seed in zip(query_list, allocations, child_seeds, strict=True):
        child_int = int(child_seed.generate_state(1, dtype=np.uint64)[0])
        releases.append(release_bounded_mean(query, epsilon=epsilon, seed=child_int, budget=budget))

    return {
        "mechanism": "bounded_mean_laplace",
        "adjacency": ADJACENCY_MODEL,
        "guarantee": "pure_epsilon_dp_mathematical_model",
        "implementation_note": (
            "Reference NumPy implementation. For high-assurance numerical guarantees, "
            "use a vetted DP backend such as OpenDP."
        ),
        "budget": budget.as_dict(),
        "releases": [release.as_dict() for release in releases],
    }

"""Optional OpenDP bounded means; public policy, private rows, noisy outputs only."""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib.metadata import version
from typing import Sequence

from privatelabbench.privacy.formal import ADJACENCY_MODEL, PrivacyBudget


def _opendp():
    try:
        import opendp.prelude as dp
    except ImportError as exc:
        raise ValueError(
            "Install private-lab-bench[opendp] for the OpenDP backend"
        ) from exc
    # Only these upstream constructors are used. Never enable honest-but-curious
    # user functions or replace OpenDP's sampler with a seeded Python RNG.
    dp.enable_features("contrib")
    return dp


@dataclass(frozen=True)
class OpenDPMeanRelease:
    """A release containing no exact mean, rows, identifiers, or input digest."""

    name: str
    value: float
    lower: float
    upper: float
    public_size: int
    epsilon: float
    sensitivity_bound: float
    backend_version: str

    def as_dict(self) -> dict:
        return {
            "schema_version": "opendp-bounded-mean/v1",
            "backend": "opendp",
            "backend_version": self.backend_version,
            "mechanism": "bounded_mean_laplace",
            "adjacency": ADJACENCY_MODEL,
            "privacy_unit": "one_row_per_individual",
            "delta": 0.0,
            **self.__dict__,
        }


@dataclass(frozen=True)
class OpenDPBoundedMean:
    """Public query policy for a fixed-size, replace-one row-level DP mean.

    Bounds, size, name, epsilon, and the decision to release must be public and
    chosen independently of private values. Repeated observations of one person
    must be reduced to one bounded contribution before using this interface.
    """

    name: str
    lower: float
    upper: float
    public_size: int
    epsilon: float

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("A public nonempty query name is required")
        if type(self.public_size) is not int or not 1 <= self.public_size <= 1_000_000:
            raise ValueError("public_size must be an integer between 1 and 1000000")
        if (
            not all(math.isfinite(x) for x in (self.lower, self.upper, self.epsilon))
            or self.lower >= self.upper
            or not math.isfinite(self.upper - self.lower)
            or self.epsilon <= 0
        ):
            raise ValueError(
                "Finite ordered public bounds and positive epsilon required"
            )

    def measurement(self):
        """Build the complete upstream clamp/mean/noise chain, without data."""
        dp = _opendp()
        space = (
            dp.vector_domain(dp.atom_domain(T=float, nan=False), size=self.public_size),
            dp.symmetric_distance(),
        )
        aggregate = (
            space
            >> dp.t.then_clamp(bounds=(float(self.lower), float(self.upper)))
            >> dp.t.then_mean()
        )
        # Replace-one means one deletion plus one insertion: distance TWO.
        # OpenDP's map includes numerical error; (upper-lower)/n alone does not.
        measurement = dp.binary_search_chain(
            lambda scale: aggregate >> dp.m.then_laplace(scale=scale),
            d_in=2,
            d_out=float(self.epsilon),
        )
        if not measurement.check(2, float(self.epsilon)):
            raise ValueError("OpenDP could not certify the requested privacy bound")
        return measurement, float(aggregate.map(2))

    def release(
        self, values: Sequence[float], *, budget: PrivacyBudget
    ) -> OpenDPMeanRelease:
        """Charge a shared local ledger before sampling; failures are not refunded.

        Keep the SAME ledger for every release about the protected population.
        The ledger is in-memory and sequential, not a concurrent or durable store.
        Validation errors must remain local; they are not DP releases.
        """
        if not isinstance(budget, PrivacyBudget):
            raise ValueError("An explicit shared PrivacyBudget is required")
        if len(values) != self.public_size:
            raise ValueError("Input does not match the declared public size")
        if any(isinstance(x, (bool, str, bytes)) for x in values):
            raise ValueError("Input requires finite numeric values")
        try:
            snapshot = [float(x) for x in values]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Input requires finite numeric values") from exc
        if not all(math.isfinite(x) for x in snapshot):
            raise ValueError("Input requires finite numeric values")
        measurement, sensitivity = self.measurement()
        if not measurement.input_domain.member(snapshot):
            raise ValueError("Input is outside the certified OpenDP domain")
        budget.spend(label=self.name, epsilon=self.epsilon)
        # Nothing that can expose a new random sample precedes this budget charge.
        value = float(measurement(snapshot))
        if not math.isfinite(value):
            raise ValueError(
                "OpenDP returned a nonfinite release; budget remains spent"
            )
        return OpenDPMeanRelease(
            self.name,
            value,
            float(self.lower),
            float(self.upper),
            self.public_size,
            float(self.epsilon),
            sensitivity,
            version("opendp"),
        )

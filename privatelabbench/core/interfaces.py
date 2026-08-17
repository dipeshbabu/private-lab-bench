from __future__ import annotations

from typing import Any, Mapping, Protocol, TypeVar

DatasetT = TypeVar("DatasetT", contravariant=True)


class Task(Protocol):
    """Runnable scientific evaluation task."""

    id: str
    description: str

    def run(self, config: Any) -> dict[str, Any]:
        """Run the task and return a normalized summary."""


class DatasetAdapter(Protocol):
    """Loads a domain-specific dataset into a model/evaluation-ready object."""

    name: str

    def load(self, source: str, **kwargs: Any) -> Any:
        """Load a dataset from a local source."""


class ModelAdapter(Protocol[DatasetT]):
    """Evaluates a model against a dataset without assuming a scientific domain."""

    name: str

    def evaluate(
        self,
        dataset: DatasetT,
        *,
        test_size: float = 0.25,
        seed: int = 13,
    ) -> dict[str, object]:
        """Train/evaluate or evaluate a model and return a normalized result payload."""


class Metric(Protocol):
    """Computes one evaluation metric."""

    name: str

    def compute(self, y_true: Any, y_pred: Any) -> float:
        """Return a scalar metric value."""


class Slice(Protocol):
    """Computes aggregate diagnostics for a named subset or grouping."""

    name: str

    def compute(self, records: Any) -> Mapping[str, Any]:
        """Return aggregate slice diagnostics."""


class PrivacyAudit(Protocol):
    """Runs a privacy-oriented audit and returns aggregate findings."""

    name: str

    def evaluate(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return aggregate privacy-audit results."""


class ArtifactWriter(Protocol):
    """Writes a reproducible evaluation artifact."""

    name: str

    def write(self, result: Mapping[str, Any], destination: str) -> str:
        """Write an artifact and return its path."""

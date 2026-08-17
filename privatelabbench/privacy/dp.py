from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Mapping, Protocol

import numpy as np


LEGACY_DP_ALIAS = "dp"
METRIC_PERTURBATION = "metric_perturbation"
NO_PRIVACY = "none"


@dataclass(frozen=True)
class PrivacyConfig:
    """Configuration for aggregate metric release.

    `metric_perturbation` adds heuristic Laplace noise to already-computed metrics.
    It does not establish query sensitivity or composition and therefore carries no
    differential-privacy guarantee. The legacy `dp` spelling is retained only as a
    deprecated alias for `metric_perturbation`.
    """

    mode: str = NO_PRIVACY
    epsilon: float = 8.0
    sensitivity: float = 1.0
    seed: int = 13

    @property
    def normalized_mode(self) -> str:
        return METRIC_PERTURBATION if self.mode == LEGACY_DP_ALIAS else self.mode

    @property
    def uses_legacy_dp_alias(self) -> bool:
        return self.mode == LEGACY_DP_ALIAS

    @property
    def guarantee_level(self) -> str:
        if self.normalized_mode == NO_PRIVACY:
            return "none"
        return "heuristic_no_dp_guarantee"

    def validate(self) -> None:
        if self.mode not in {NO_PRIVACY, METRIC_PERTURBATION, LEGACY_DP_ALIAS}:
            raise ValueError("privacy mode must be 'none' or 'metric_perturbation' ('dp' is a deprecated alias)")
        if self.epsilon <= 0:
            raise ValueError("epsilon must be positive")
        if self.sensitivity <= 0:
            raise ValueError("sensitivity must be positive")
        if self.uses_legacy_dp_alias:
            warnings.warn(
                "privacy.mode='dp' is deprecated and means heuristic metric_perturbation; "
                "it does not provide a framework-verified differential-privacy guarantee",
                FutureWarning,
                stacklevel=2,
            )

    def report_metadata(self) -> dict[str, object]:
        self.validate()
        return {
            "configured_mode": self.mode,
            "mode": self.normalized_mode,
            "mechanism": self.normalized_mode,
            "guarantee_level": self.guarantee_level,
            "epsilon_like_parameter": float(self.epsilon),
            "user_supplied_scale_sensitivity": float(self.sensitivity),
            "seed": int(self.seed),
            "legacy_dp_alias": self.uses_legacy_dp_alias,
            "formal_dp": False,
        }


@dataclass(frozen=True)
class MetricRelease:
    metrics: dict[str, float]
    metadata: dict[str, object]


class MetricReleaseMechanism(Protocol):
    name: str
    guarantee_level: str

    def release(self, metrics: Mapping[str, float], config: PrivacyConfig) -> MetricRelease: ...


class ExactMetricRelease:
    name = NO_PRIVACY
    guarantee_level = "none"

    def release(self, metrics: Mapping[str, float], config: PrivacyConfig) -> MetricRelease:
        clean = {key: float(value) for key, value in metrics.items()}
        return MetricRelease(
            metrics=clean,
            metadata={
                **config.report_metadata(),
                "mechanism": self.name,
                "guarantee_level": self.guarantee_level,
                "formal_dp": False,
                "note": "Exact aggregate metrics; no privacy noise is applied.",
            },
        )


class MetricPerturbationRelease:
    name = METRIC_PERTURBATION
    guarantee_level = "heuristic_no_dp_guarantee"

    def release(self, metrics: Mapping[str, float], config: PrivacyConfig) -> MetricRelease:
        clean = {key: float(value) for key, value in metrics.items()}
        rng = np.random.default_rng(config.seed)
        scale = config.sensitivity / config.epsilon
        released: dict[str, float] = {}
        for key, value in clean.items():
            if np.isnan(value):
                released[key] = value
            else:
                released[key] = float(value + rng.laplace(0.0, scale))
        return MetricRelease(
            metrics=released,
            metadata={
                **config.report_metadata(),
                "mechanism": self.name,
                "guarantee_level": self.guarantee_level,
                "formal_dp": False,
                "noise_distribution": "laplace",
                "noise_scale": float(scale),
                "note": (
                    "Heuristic perturbation of already-computed metrics. The configured sensitivity "
                    "is a noise-scale parameter supplied by the user, not a framework-verified global sensitivity."
                ),
            },
        )


_MECHANISMS: dict[str, MetricReleaseMechanism] = {
    NO_PRIVACY: ExactMetricRelease(),
    METRIC_PERTURBATION: MetricPerturbationRelease(),
}


def get_metric_release_mechanism(config: PrivacyConfig) -> MetricReleaseMechanism:
    config.validate()
    return _MECHANISMS[config.normalized_mode]


def release_metrics(metrics: Mapping[str, float], config: PrivacyConfig) -> MetricRelease:
    return get_metric_release_mechanism(config).release(metrics, config)


def privatize_metrics(metrics: Mapping[str, float], config: PrivacyConfig) -> dict[str, float]:
    """Compatibility wrapper returning only released metric values.

    The name is retained for API compatibility. New code should use `release_metrics`
    so mechanism/guarantee metadata is not discarded.
    """

    return release_metrics(metrics, config).metrics


def privacy_summary(config: PrivacyConfig) -> str:
    config.validate()
    if config.normalized_mode == NO_PRIVACY:
        return "Exact aggregate metrics are reported; no privacy mechanism is applied."
    legacy = " The configured mode 'dp' is a deprecated alias." if config.uses_legacy_dp_alias else ""
    return (
        "Heuristic metric perturbation is applied with Laplace noise "
        f"(epsilon-like parameter={config.epsilon:g}, user-supplied sensitivity={config.sensitivity:g}). "
        "This is not a formal differential-privacy guarantee because query sensitivity and composition are not verified."
        + legacy
    )

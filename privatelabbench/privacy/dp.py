from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import numpy as np


@dataclass(frozen=True)
class PrivacyConfig:
    mode: str = "none"
    epsilon: float = 8.0
    sensitivity: float = 1.0
    seed: int = 13

    def validate(self) -> None:
        if self.mode not in {"none", "dp"}:
            raise ValueError("privacy mode must be 'none' or 'dp'")
        if self.epsilon <= 0:
            raise ValueError("epsilon must be positive")
        if self.sensitivity <= 0:
            raise ValueError("sensitivity must be positive")


def privatize_metrics(metrics: Mapping[str, float], config: PrivacyConfig) -> dict[str, float]:
    config.validate()
    clean = {k: float(v) for k, v in metrics.items()}
    if config.mode == "none":
        return clean

    rng = np.random.default_rng(config.seed)
    scale = config.sensitivity / config.epsilon
    out: dict[str, float] = {}
    for key, value in clean.items():
        if math.isnan(value):
            out[key] = value
        else:
            out[key] = float(value + rng.laplace(0.0, scale))
    return out


def privacy_summary(config: PrivacyConfig) -> str:
    config.validate()
    if config.mode == "none":
        return "No metric noise applied. Use --privacy dp for DP-style local metric reporting."
    return f"DP-style metric noise applied with epsilon={config.epsilon:g}, sensitivity={config.sensitivity:g}."

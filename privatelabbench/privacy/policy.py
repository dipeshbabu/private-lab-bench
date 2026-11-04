from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any, Mapping

RISK_ORDER = {"low": 0, "moderate": 1, "high": 2}


@dataclass(frozen=True)
class PrivacyRiskPolicy:
    max_level: str = "high"
    max_member_advantage: float | None = None
    max_attack_auc: float | None = None
    require_attack: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.max_level, str) or self.max_level not in RISK_ORDER:
            raise ValueError(
                "privacy.risk_policy.max_level must be low, moderate, or high."
            )
        if not isinstance(self.require_attack, bool):
            raise ValueError("privacy.risk_policy.require_attack must be a boolean.")
        for name in ("max_member_advantage", "max_attack_auc"):
            threshold = getattr(self, name)
            if threshold is not None and (
                isinstance(threshold, bool)
                or not isinstance(threshold, Real)
                or not math.isfinite(threshold)
                or not 0 <= threshold <= 1
            ):
                raise ValueError(
                    f"privacy.risk_policy.{name} must be a finite number in [0, 1]."
                )

    @classmethod
    def from_config(cls, value: Mapping[str, Any] | None) -> "PrivacyRiskPolicy":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("privacy.risk_policy must be a mapping.")
        unknown = set(value) - {
            "max_level",
            "max_member_advantage",
            "max_attack_auc",
            "require_attack",
        }
        if unknown:
            raise ValueError(
                "Unknown privacy.risk_policy fields: "
                + ", ".join(sorted(map(str, unknown)))
            )
        max_level = str(value.get("max_level", "high")).strip().lower()
        if max_level not in RISK_ORDER:
            raise ValueError(
                "privacy.risk_policy.max_level must be low, moderate, or high."
            )
        max_member_advantage = value.get("max_member_advantage")
        max_attack_auc = value.get("max_attack_auc")
        return cls(
            max_level=max_level,
            max_member_advantage=max_member_advantage,
            max_attack_auc=max_attack_auc,
            require_attack=value.get("require_attack", False),
        )


def evaluate_privacy_gate(
    privacy_risk: Mapping[str, Any] | None,
    policy: PrivacyRiskPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or PrivacyRiskPolicy()
    violations: list[str] = []
    if not privacy_risk:
        if (
            policy.require_attack
            or policy.max_level != "high"
            or policy.max_member_advantage is not None
            or policy.max_attack_auc is not None
        ):
            violations.append("privacy_attack_required")
        return {
            "status": "fail" if violations else "pass",
            "publishable": not violations,
            "policy": {
                "max_level": policy.max_level,
                "max_member_advantage": policy.max_member_advantage,
                "max_attack_auc": policy.max_attack_auc,
                "require_attack": policy.require_attack,
            },
            "observed": {},
            "violations": violations,
        }

    risk_level = str(privacy_risk.get("risk_level", "unknown")).strip().lower()
    if risk_level not in RISK_ORDER:
        violations.append("unknown_risk_level")
    elif RISK_ORDER[risk_level] > RISK_ORDER[policy.max_level]:
        violations.append("risk_level_exceeds_policy")

    member_advantage = privacy_risk.get("member_advantage")
    if policy.max_member_advantage is not None:
        if (
            not isinstance(member_advantage, (int, float))
            or isinstance(member_advantage, bool)
            or not math.isfinite(member_advantage)
        ):
            violations.append("member_advantage_required")
        elif float(member_advantage) > policy.max_member_advantage:
            violations.append("member_advantage_exceeds_policy")

    attack_auc = privacy_risk.get("attack_auc")
    if policy.max_attack_auc is not None:
        if (
            not isinstance(attack_auc, (int, float))
            or isinstance(attack_auc, bool)
            or not math.isfinite(attack_auc)
        ):
            violations.append("attack_auc_required")
        elif float(attack_auc) > policy.max_attack_auc:
            violations.append("attack_auc_exceeds_policy")

    return {
        "status": "fail" if violations else "pass",
        "publishable": not violations,
        "policy": {
            "max_level": policy.max_level,
            "max_member_advantage": policy.max_member_advantage,
            "max_attack_auc": policy.max_attack_auc,
            "require_attack": policy.require_attack,
        },
        "observed": {
            "risk_level": risk_level,
            "member_advantage": member_advantage,
            "attack_auc": attack_auc,
        },
        "violations": violations,
    }

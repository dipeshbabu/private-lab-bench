from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


RISK_ORDER = {"low": 0, "moderate": 1, "high": 2}


@dataclass(frozen=True)
class PrivacyRiskPolicy:
    max_level: str = "high"
    max_member_advantage: float | None = None
    max_attack_auc: float | None = None
    require_attack: bool = False

    @classmethod
    def from_config(cls, value: Mapping[str, Any] | None) -> "PrivacyRiskPolicy":
        if not value:
            return cls()
        max_level = str(value.get("max_level", "high")).strip().lower()
        if max_level not in RISK_ORDER:
            raise ValueError("privacy.risk_policy.max_level must be low, moderate, or high.")
        max_member_advantage = value.get("max_member_advantage")
        max_attack_auc = value.get("max_attack_auc")
        return cls(
            max_level=max_level,
            max_member_advantage=float(max_member_advantage) if max_member_advantage is not None else None,
            max_attack_auc=float(max_attack_auc) if max_attack_auc is not None else None,
            require_attack=bool(value.get("require_attack", False)),
        )


def evaluate_privacy_gate(
    privacy_risk: Mapping[str, Any] | None,
    policy: PrivacyRiskPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or PrivacyRiskPolicy()
    violations: list[str] = []
    if not privacy_risk:
        if policy.require_attack:
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

    risk_level = str(privacy_risk.get("risk_level", "low")).strip().lower()
    if risk_level not in RISK_ORDER:
        violations.append("unknown_risk_level")
    elif RISK_ORDER[risk_level] > RISK_ORDER[policy.max_level]:
        violations.append("risk_level_exceeds_policy")

    member_advantage = privacy_risk.get("member_advantage")
    if policy.max_member_advantage is not None and member_advantage is not None:
        if float(member_advantage) > policy.max_member_advantage:
            violations.append("member_advantage_exceeds_policy")

    attack_auc = privacy_risk.get("attack_auc")
    if policy.max_attack_auc is not None and attack_auc is not None:
        if float(attack_auc) > policy.max_attack_auc:
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

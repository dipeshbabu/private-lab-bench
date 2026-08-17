from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


PrivacyAttack = Callable[..., dict[str, object]]


@dataclass(frozen=True)
class PrivacyAttackSpec:
    id: str
    runner: PrivacyAttack
    description: str
    evidence_level: str = "empirical_audit"
    baseline: bool = False


_ATTACKS: dict[str, PrivacyAttackSpec] = {}


def register_privacy_attack(
    attack_id: str,
    runner: PrivacyAttack,
    *,
    description: str = "",
    evidence_level: str = "empirical_audit",
    baseline: bool = False,
) -> PrivacyAttackSpec:
    normalized = attack_id.strip().lower()
    if not normalized:
        raise ValueError("privacy attack id must not be empty")
    if normalized in _ATTACKS:
        raise ValueError(f"privacy attack '{normalized}' is already registered")
    spec = PrivacyAttackSpec(
        id=normalized,
        runner=runner,
        description=description,
        evidence_level=evidence_level,
        baseline=baseline,
    )
    _ATTACKS[normalized] = spec
    return spec


def has_privacy_attack(attack_id: str) -> bool:
    return attack_id.strip().lower() in _ATTACKS


def get_privacy_attack(attack_id: str) -> PrivacyAttackSpec:
    normalized = attack_id.strip().lower()
    if normalized not in _ATTACKS:
        raise KeyError(f"unknown privacy attack: {normalized}")
    return _ATTACKS[normalized]


def list_privacy_attacks() -> tuple[PrivacyAttackSpec, ...]:
    return tuple(_ATTACKS[key] for key in sorted(_ATTACKS))


def clear_privacy_attacks_for_testing() -> None:
    _ATTACKS.clear()

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from privatelabbench.config import RunnerConfig

TaskRunner = Callable[["RunnerConfig"], dict[str, Any]]
ENTRYPOINT_GROUP = "privatelabbench.tasks"


@dataclass(frozen=True)
class TaskSpec:
    """A registered evaluation task."""

    id: str
    runner: TaskRunner
    description: str = ""
    source: str = "builtin"


_TASKS: dict[str, TaskSpec] = {}
_ENTRYPOINTS_DISCOVERED = False


def _normalize_task_id(task_id: str) -> str:
    normalized = task_id.strip().lower()
    if not normalized:
        raise ValueError("Task id cannot be empty.")
    if any(char.isspace() for char in normalized):
        raise ValueError("Task id cannot contain whitespace.")
    return normalized


def register_task(
    task_id: str,
    runner: TaskRunner,
    *,
    description: str = "",
    source: str = "builtin",
    replace: bool = False,
) -> TaskSpec:
    """Register one evaluation task."""

    normalized = _normalize_task_id(task_id)
    if normalized in _TASKS and not replace:
        raise ValueError(f"Task '{normalized}' is already registered.")
    spec = TaskSpec(
        id=normalized,
        runner=runner,
        description=description.strip(),
        source=source,
    )
    _TASKS[normalized] = spec
    return spec


def has_task(task_id: str) -> bool:
    return _normalize_task_id(task_id) in _TASKS


def get_task(task_id: str) -> TaskSpec:
    normalized = _normalize_task_id(task_id)
    try:
        return _TASKS[normalized]
    except KeyError as exc:
        available = ", ".join(sorted(_TASKS)) or "(none registered)"
        raise ValueError(
            f"Unknown task '{normalized}'. Available tasks: {available}"
        ) from exc


def list_tasks() -> tuple[TaskSpec, ...]:
    return tuple(_TASKS[key] for key in sorted(_TASKS))


def clear_tasks() -> None:
    """Clear the in-process registry. Intended for tests."""

    _TASKS.clear()


def _coerce_entrypoint(value: Any, *, source: str) -> Iterable[TaskSpec]:
    if isinstance(value, TaskSpec):
        yield TaskSpec(
            id=value.id,
            runner=value.runner,
            description=value.description,
            source=source,
        )
        return

    if callable(value):
        produced = value()
        if isinstance(produced, TaskSpec):
            yield TaskSpec(
                id=produced.id,
                runner=produced.runner,
                description=produced.description,
                source=source,
            )
            return
        if isinstance(produced, Iterable):
            for item in produced:
                if not isinstance(item, TaskSpec):
                    raise TypeError(
                        f"Task entry point {source} returned a non-TaskSpec item."
                    )
                yield TaskSpec(
                    id=item.id,
                    runner=item.runner,
                    description=item.description,
                    source=source,
                )
            return

    raise TypeError(
        f"Task entry point {source} must expose a TaskSpec or a callable returning TaskSpec objects."
    )


def discover_entrypoint_tasks(*, force: bool = False) -> tuple[TaskSpec, ...]:
    """Discover third-party task plugins through Python entry points."""

    global _ENTRYPOINTS_DISCOVERED
    if _ENTRYPOINTS_DISCOVERED and not force:
        return ()

    discovered: list[TaskSpec] = []
    entry_points = metadata.entry_points()
    selected = (
        entry_points.select(group=ENTRYPOINT_GROUP)
        if hasattr(entry_points, "select")
        else entry_points.get(ENTRYPOINT_GROUP, ())
    )
    for entry_point in selected:
        source = f"entrypoint:{entry_point.name}"
        for spec in _coerce_entrypoint(entry_point.load(), source=source):
            register_task(
                spec.id,
                spec.runner,
                description=spec.description,
                source=spec.source,
            )
            discovered.append(get_task(spec.id))

    _ENTRYPOINTS_DISCOVERED = True
    return tuple(discovered)

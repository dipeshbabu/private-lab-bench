"""Core extension interfaces and task registry for PrivateLabBench."""

from privatelabbench.core.interfaces import (
    ArtifactWriter,
    DatasetAdapter,
    Metric,
    ModelAdapter,
    PrivacyAudit,
    Slice,
    Task,
)
from privatelabbench.core.registry import (
    TaskSpec,
    discover_entrypoint_tasks,
    get_task,
    has_task,
    list_tasks,
    register_task,
)

__all__ = [
    "ArtifactWriter",
    "DatasetAdapter",
    "Metric",
    "ModelAdapter",
    "PrivacyAudit",
    "Slice",
    "Task",
    "TaskSpec",
    "discover_entrypoint_tasks",
    "get_task",
    "has_task",
    "list_tasks",
    "register_task",
]

"""Installed-wheel fixture exercising the public task entry-point contract."""

from privatelabbench.core.registry import TaskSpec, get_task


def run(config):
    return get_task("tabular").runner(config)


def provider():
    return TaskSpec(
        id="ci-installed-plugin",
        runner=run,
        description="Synthetic installed task-plugin fixture",
    )

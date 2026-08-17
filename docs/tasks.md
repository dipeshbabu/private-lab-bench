# Tasks and plugins

## Discover tasks

```bash
plb list-tasks
```

Built-in tasks currently include `predictions`, `tabular`, `molecules`, `multi-site`, and the legacy `federated` alias.

## Prefer prediction tables first

Before creating a task plugin, check whether the use case can be represented as `prediction-table/v1`. Domain-specific fields can remain metadata and configured slices while the evaluator stays generic.

## Third-party task entry points

External packages can register a `TaskSpec` through:

```toml
[project.entry-points."privatelabbench.tasks"]
my-task = "my_package.plugin:task_spec"
```

The task runner receives `RunnerConfig` and returns the standard run-summary fields expected by reports, manifests, and receipts.

A plugin is preferable to a core task when it needs heavyweight scientific frameworks, remote services, model runtimes, or specialist dependencies that most users do not need.

See the contributor guide in the repository for review and compatibility expectations.

# PrivateLabBench Pilot Checklist

Use this checklist before starting a customer pilot for private scientific AI evaluation.

## Customer qualification

- [ ] Customer has proprietary scientific data.
- [ ] Customer has at least one model or model output column to evaluate.
- [ ] Customer has one narrow model claim to prove or disprove.
- [ ] Customer can run a local Python package or Docker image.
- [ ] Customer is comfortable sharing sanitized evidence metadata and local reports.

## Data readiness

- [ ] CSV contains a target column.
- [ ] CSV contains a prediction column for the `predictions` workflow.
- [ ] Task type is clear: `regression` or `classification`.
- [ ] Missing labels/predictions are understood.
- [ ] Sensitive identifiers are removed or not needed.

## Config readiness

- [ ] `project` is set.
- [ ] `workflow` is set to `predictions`, `molecules`, or `federated`.
- [ ] `input.path` or `input.client_dir` points to local data.
- [ ] `target_column` is correct.
- [ ] `prediction_column` is correct for prediction evaluation.
- [ ] Privacy mode and epsilon are selected.
- [ ] Markdown and JSON report paths are selected.

## Local execution

- [ ] `privatelabbench run <config.yaml>` succeeds locally.
- [ ] Markdown report is produced.
- [ ] JSON report is produced.
- [ ] Report contains expected metrics.
- [ ] Raw CSV is not uploaded anywhere by the runner.

## Docker execution

- [ ] Docker image builds.
- [ ] Customer data directory is mounted read-only when possible.
- [ ] Reports directory is mounted for output.
- [ ] Same config works inside the container.

## Pilot deliverables

- [ ] Model-claim evidence report.
- [ ] Baseline or incumbent comparison.
- [ ] Private reported metrics.
- [ ] Dataset or prediction summary.
- [ ] Model comparison if multiple prediction files are available.
- [ ] Signed report or manifest verification output.
- [ ] Recommendation for next integration step.

## Commercial next step

- [ ] Customer agrees on success metric.
- [ ] Customer identifies internal owner.
- [ ] Customer identifies security or procurement constraints.
- [ ] Follow-on paid pilot or annual contract path is clear.

# Recommended GitHub Repository Settings

These are the intended discovery/community settings for the public PrivateLabBench repository. They are repository metadata/settings rather than source-controlled behavior.

## Description

```text
Local-first evaluation for scientific machine learning on private data.
```

## Topics

Recommended topics:

```text
scientific-machine-learning
machine-learning-evaluation
private-data
reproducibility
privacy
privacy-auditing
benchmarking
scientific-ai
open-source
```

## Discussions

Enable GitHub Discussions when the repository becomes public and there is enough community traffic to justify separating Q&A/ideas from actionable issues. Until then, structured issue templates are the supported contribution path.

## Labels

Recommended labels:

```text
good first issue
help wanted
task
metric
privacy
docs
benchmark-pack
schema
artifact
breaking-change
dependencies
ci
tests
needs-triage
```

Use GitHub's standard `bug`, `enhancement`, and `documentation` labels where available.

## Security

Enable GitHub private vulnerability reporting before broad public launch so `SECURITY.md` can point directly to the private reporting form.

## Branch/review policy

Use pull requests and squash merge only after all checks on the current commit pass. Dependency updates follow this rule too. Schema/privacy/security changes need explicit maintainer review even when tests pass. See the maintenance-bot section in `CONTRIBUTING.md` for schedules and automatic labels.

## Documentation hosting

GitHub Pages uses GitHub Actions as its publishing source. The `docs.yml`
workflow deploys the tested main commit after CI succeeds, using the
`github-pages` environment and a short-lived deployment token. The public site
is https://dipeshbabu.github.io/private-lab-bench/.

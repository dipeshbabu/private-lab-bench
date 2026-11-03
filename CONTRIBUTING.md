# Contributing to PrivateLabBench

Thanks for helping improve PrivateLabBench. The project is a community-first, local evaluation framework for scientific machine learning on private or restricted data.

The main design constraint is simple: **the core should remain useful without hosted infrastructure, private-data upload, or a specific model framework.**

## Before you start

Use a GitHub no-reply author/committer email before pushing commits. The history
audit rejects unreviewed email metadata. An author who deliberately wants a public
email may request a consented exception in `audit/public_release_manifest.yaml`.
After the 2026-11-03 email rewrite, re-clone or carefully rebase unpublished work;
merging an old local branch can restore the retired metadata. Maintainership
squash merges should select the approved no-reply author email explicitly.

For a bug fix or small documentation improvement, a pull request is usually enough.

For a new task, benchmark pack, privacy method, public API, or behavior that changes an artifact schema, please open the matching issue template first. That gives maintainers and other contributors a chance to agree on scope before a larger implementation is written.

Security vulnerabilities should follow [`SECURITY.md`](SECURITY.md), not a public issue.

## Development setup

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
python -m pre_commit install
python -m pre_commit run --all-files
pytest -q
```

Optional RDKit work:

```bash
pip install -e '.[rdkit,dev]'
```

Run the main user paths before opening a PR:

```bash
plb list-tasks
plb list-packs
plb validate-config configs/tabular_eval.yaml
plb run configs/tabular_eval.yaml
plb verify reports/tabular_demo_receipt.shareable.json
```

If your change touches Docker behavior:

```bash
docker build -t privatelabbench:dev .
docker run --rm privatelabbench:dev list-tasks
```

CI runs tests on Python 3.10, 3.11, and 3.12 plus Docker and package checks. Its
quality job uses Python 3.11 and runs the same pre-commit hooks used locally.

## Code quality

Ruff checks Python errors, unused imports, import ordering, and formatting. Run
all checks with `python -m pre_commit run --all-files`, or use
`python -m pre_commit run ruff-check --all-files` for just the linter.
The hook may fix files; review the changes and stage them before committing.

Hook revisions live in `.pre-commit-config.yaml`, and Ruff settings live in
`pyproject.toml`. Keep these checks enabled when changing code. The other hooks
validate YAML, TOML, and JSON, detect conflict markers and large files, and clean
text whitespace. Byte-pinned JSON/CSV assets are excluded from whitespace edits.

To check a change before opening a pull request, push it on a `codex/` branch.
CI and the full-history public-release audit also run on pushes to these branches.
Wait for both workflows to succeed on the current commit before opening the PR,
then confirm the PR checks pass before merging. Remove the branch after merge.

## Maintenance bots

Dependabot checks Python dependencies, GitHub Actions, pre-commit hooks, and the
Docker base image every Monday morning in America/New_York. Compatible updates
are grouped where appropriate; larger upgrades get separate PRs. Updates follow
the same requirement for green CI and squash merging as other contributions.

The pinned legacy TDC loader, Hugging Face Hub, and setuptools compatibility stack
need a manual upstream-parity review. NumPy/Pandas constraint changes and Python
Docker minor-line upgrades also need explicit compatibility review. These limits
are recorded in `.github/dependabot.yml`.

New issues and PRs receive `needs-triage` and relevant type/domain labels from
their titles and changed file names. Edits can add labels; the bot preserves
manual labels and triage decisions. Dependabot supplies its own configured labels.

The label workflow runs on trusted default-branch code, including for fork PRs;
it uses issue/PR metadata and never executes submitted code. To change its rules,
run `node --test .github/scripts/auto-label.test.cjs` and the repository checks.
Maintainers can use the Auto labels workflow's manual input to label a selected
existing issue or PR.

## Architecture in one page

The important layers are:

```text
prediction table / task-specific input
              ↓
          Task registry
              ↓
   evaluation + metrics + slices
              ↓
     privacy audits / release
              ↓
       JSON + Markdown report
              ↓
         run manifest
              ↓
 local receipt + shareable receipt
```

Core extension protocols live in `privatelabbench.core`:

- `Task`
- `DatasetAdapter`
- `ModelAdapter`
- `Metric`
- `Slice`
- `PrivacyAudit`
- `ArtifactWriter`

The preferred low-friction interface is `prediction-table/v1`. A researcher should normally be able to evaluate model outputs without integrating the model implementation.

## Where should my contribution live?

### Core

A feature belongs in core when it is broadly useful across scientific domains and has a small dependency footprint. Examples: schema validation, generic metrics, artifact integrity, task discovery, or domain-neutral slice infrastructure.

### External task/plugin package

Prefer an external plugin when a task requires a heavy framework, specialist scientific dependency, large model, remote service, or domain-specific lifecycle that most PrivateLabBench users do not need.

### Benchmark pack

Use a benchmark pack when the contribution is primarily a reproducible evaluation protocol plus small/synthetic prediction examples. Packs should not become mirrors of large public datasets.

## Adding a task plugin

Third-party packages can expose a `TaskSpec` using the `privatelabbench.tasks` entry-point group:

```toml
[project.entry-points."privatelabbench.tasks"]
my-task = "my_package.plugin:task_spec"
```

A minimal plugin module can construct a `TaskSpec` whose runner accepts a `RunnerConfig` and returns the normal run summary fields used by manifests/receipts.

Before proposing a new built-in task, prove that the generic prediction-table path cannot represent the use case cleanly.

## Adding metrics or slices

A metric/slice contribution should include:

1. a precise definition;
2. supported task types and input assumptions;
3. behavior for degenerate/small samples;
4. tests with known values;
5. documentation of whether the output is safe for shareable receipts.

Do not silently emit row-level values into aggregate artifacts.

## Adding a privacy audit

Privacy attacks are empirical audits, not guarantees. Register new attacks separately from release mechanisms and include:

- threat model;
- attacker knowledge/access assumptions;
- output interpretation;
- known failure modes;
- computational cost;
- tests on positive and negative controls.

The existing loss-threshold membership attack is intentionally labeled a baseline.

Formal privacy mechanism work must specify adjacency, bounds/sensitivity, composition, and implementation assumptions. See [`docs/privacy.md`](docs/privacy.md).

## Adding a benchmark pack

Follow [`docs/benchmark_packs.md`](docs/benchmark_packs.md). Every pack must declare:

- stable ID/version;
- task/domain;
- license and provenance;
- runnable config;
- small/synthetic or clearly redistributable prediction data;
- known-good shareable receipt;
- regression tests.

Never commit private/restricted samples, credentials, large datasets, or model weights as a benchmark pack.

## Artifact/schema changes

`prediction-table/v1`, `evaluation-receipt/v1`, and `benchmark-pack/v1` are versioned protocols. Backward-incompatible changes require either a schema-version bump or an explicit migration/compatibility path with tests.

Do not change artifact meaning while leaving the version unchanged.

## Testing expectations

At minimum, new behavior should have unit tests. For user-facing workflows, prefer an end-to-end config/CLI test as well.

Useful commands:

```bash
pytest -q
pytest -q tests/test_prediction_eval.py
pytest -q tests/test_receipt.py
pytest -q tests/test_benchmark_packs.py
```

Tests should be deterministic. If randomness is part of the method, expose/use a seed.

## Code style

- Keep modules focused and explicit.
- Prefer typed, small interfaces over framework-specific abstractions.
- Keep heavyweight dependencies optional.
- Avoid network calls as a side effect of evaluation.
- Preserve local-first behavior.
- Produce actionable validation errors.
- Do not weaken privacy wording to make a feature sound stronger.
- Avoid unnecessary compatibility breaks.

## Documentation expectations

Update the relevant concept document when a public interface changes. Examples should be runnable and should not claim features or privacy guarantees that the code does not provide.

## Pull requests

Please keep a PR focused on one logical issue. Include:

- what changed;
- why;
- user/developer impact;
- compatibility implications;
- privacy/data-sharing implications when relevant;
- tests/checks run.

Small, reviewable PRs are preferred over broad refactors that combine unrelated work.

## Review and governance

See [`GOVERNANCE.md`](GOVERNANCE.md) for maintainer responsibilities, decision rules, compatibility expectations, and the path from contributor to maintainer.

## Community standards

Participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Be precise, constructive, and respectful. Technical disagreement is welcome; personal attacks, harassment, and discriminatory behavior are not.

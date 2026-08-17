# Installation

## Current repository install

Until the first PyPI release is actually published, install from a checkout:

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
python -m pip install -e .
```

Development install:

```bash
python -m pip install -e '.[dev]'
```

Optional RDKit support:

```bash
python -m pip install -e '.[rdkit]'
```

Documentation tooling:

```bash
python -m pip install -e '.[docs]'
mkdocs serve
```

## PyPI release path

The package metadata and release workflow are prepared for:

```bash
pip install private-lab-bench
```

Do not treat that command as live until a real release appears on PyPI. The release maintainer must first configure PyPI Trusted Publishing for this repository/environment and push a version tag that matches `pyproject.toml` and `privatelabbench.__version__`.

## Supported Python

The project tests Python 3.10, 3.11, and 3.12.

## Verify the installation

```bash
plb --help
plb list-tasks
plb list-packs
```

A wheel-install CI job runs these commands from outside the source checkout to catch missing package-data problems.

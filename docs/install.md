# Installation

## Install v0.1.2

Use Python 3.10 or later in an activated virtual environment:

```bash
python -m pip install private-lab-bench==0.1.2
```

Optional RDKit support:

```bash
python -m pip install 'private-lab-bench[rdkit]==0.1.2'
```

The [quickstart notebook](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/v0.1.2/examples/notebooks/quickstart.ipynb) installs the same release and runs a bundled synthetic benchmark without a repository checkout.

## Source and development installs

To reproduce the release from source:

```bash
git clone --branch v0.1.2 https://github.com/dipeshbabu/private-lab-bench.git
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

## Supported Python

The project tests Python 3.10, 3.11, and 3.12.

## Verify the installation

```bash
plb --help
plb list-tasks
plb list-packs
```

A wheel-install CI job runs these commands from outside the source checkout to catch missing package-data problems.

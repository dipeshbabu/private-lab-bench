---
icon: material/download-outline
---

# Installation

## Install v0.1.6

Use Python 3.10 or later in an activated virtual environment:

```bash
python -m pip install private-lab-bench==0.1.6
```

For the optional bounded-mean privacy backend:

```sh
python -m pip install 'private-lab-bench[opendp]==0.1.6'
```

See [privacy](privacy.md#optional-opendp-backend) for the public-query and
accounting assumptions. [Sandboxed inference](sandbox.md) needs an explicitly
configured Linux Docker/gVisor host and reviewed image; installing the Python
package alone does not supply that runtime.

Optional RDKit support:

```bash
python -m pip install 'private-lab-bench[rdkit]==0.1.6'
```

The [quickstart notebook](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/v0.1.6/examples/notebooks/quickstart.ipynb) installs the same release and runs a bundled synthetic benchmark without a repository checkout.

## Source and development installs

To reproduce the release from source:

```bash
git clone --branch v0.1.6 https://github.com/dipeshbabu/private-lab-bench.git
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

The development branch runs the full base suite and clean wheel/source checks
across 26 configured OS/Python combinations: CPython 3.10–3.15 and 3.14/3.15
free-threaded builds on Linux, Windows and macOS, plus Linux/Windows ARM64 on
Python 3.14. macOS Python 3.10 uses Intel runners. See the [support matrix](support.md)
for exact coverage, dependency pins and optional-integration requirements.

Support recorded for the published v0.1.6 release is available in its
[tagged support matrix](https://github.com/dipeshbabu/private-lab-bench/blob/v0.1.6/docs/support.md).

## Verify the installation

```bash
plb --help
plb list-tasks
plb list-packs
```

A wheel-install CI job runs these commands from outside the source checkout to catch missing package-data problems.

# Installation

## Install v0.1.4

Use Python 3.10 or later in an activated virtual environment:

```bash
python -m pip install private-lab-bench==0.1.4
```

For the optional bounded-mean privacy backend:

```sh
python -m pip install 'private-lab-bench[opendp]==0.1.4'
```

See [privacy](privacy.md#optional-opendp-backend) for the public-query and
accounting assumptions. [Sandboxed inference](sandbox.md) needs an explicitly
configured Linux Docker/gVisor host and reviewed image; installing the Python
package alone does not supply that runtime.

Optional RDKit support:

```bash
python -m pip install 'private-lab-bench[rdkit]==0.1.4'
```

The [quickstart notebook](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/v0.1.4/examples/notebooks/quickstart.ipynb) installs the same release and runs a bundled synthetic benchmark without a repository checkout.

## Source and development installs

To reproduce the release from source:

```bash
git clone --branch v0.1.4 https://github.com/dipeshbabu/private-lab-bench.git
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

The core has installed-wheel and source-install checks on Linux for Python
3.10–3.14, and on Windows/macOS for Python 3.12 and 3.14. Linux 3.10–3.12 also run
the full suite. Other OS/interpreter combinations remain untested. See the
[support matrix](support.md) for exact scope, representative dependency pins,
legacy Python 3.10 status, and the separate constraints for optional integrations.

## Verify the installation

```bash
plb --help
plb list-tasks
plb list-packs
```

A wheel-install CI job runs these commands from outside the source checkout to catch missing package-data problems.

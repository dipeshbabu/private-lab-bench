# Tested compatibility

The core evaluates prediction tables without a model framework or optional domain
dependencies. The [installed-distribution matrix](https://github.com/dipeshbabu/private-lab-bench/actions/workflows/compatibility.yml)
builds one wheel and source archive, then installs each in a separate clean
environment outside the checkout. A green row means the checks below passed; it
does not imply that every optional extra or every dependency version was tested.

| Python | Linux | Windows | macOS |
| --- | --- | --- | --- |
| 3.10 | Core smoke + full suite; legacy compatibility | Untested | Untested |
| 3.11 | Core smoke + full suite | Untested | Untested |
| 3.12 | Core smoke + full suite | Core smoke | Core smoke |
| 3.13 | Core smoke | Untested | Untested |
| 3.14 | Core smoke | Core smoke | Core smoke |
| 3.15 and newer | Untested | Untested | Untested |

The matrix covers normal CPython builds, not free-threaded interpreters, PyPy, or
every CPU architecture. GitHub's `ubuntu-latest`, `windows-latest`, and
`macos-latest` runners supply the tested hosts. Each run retains a small JSON
record of the actual Python/dependency versions, distribution hashes, and passed
checks. This live table follows main; PyPI metadata records the README and
classifiers bundled at each release.

Python 3.10 remains a compatibility target, but Python itself reached end of life
in October 2026. Use a maintained interpreter for new environments; see the
[Python release status](https://devguide.python.org/versions/). The package retains
`requires-python >=3.10` and adds no artificial ceiling at 3.13 or 3.14.

## What the core smoke verifies

Both installed distributions must pass `pip check`, CLI help and argument errors,
bundled package-data execution, a 48-row synthetic evaluation with uncertainty and
Unicode group names/paths, paired comparison, quality-gate exit codes, local
receipt verification, hard-link/input preservation, reserved release-state paths,
custom class labels, balanced membership diagnostics, and malformed digest
rejection. Evaluation stays local; the fixture includes no real private data.

The jobs use UTF-8 mode and the representative pins in
[`constraints/core.txt`](https://github.com/dipeshbabu/private-lab-bench/blob/main/constraints/core.txt).
The normal Linux CI still tests ordinary dependency resolution and the complete
suite on 3.10–3.12. Passing these environments does not verify every older version
permitted by the package's dependency bounds.

## Optional integrations

| Component | Dedicated tested environment | Boundary |
| --- | --- | --- |
| TDC ADMET | Linux, Python 3.11, pinned PyTDC 0.4.1 reference environment | NumPy <2 and pandas <3; follow the [TDC guide](tdc_admet.md) |
| Matbench | Linux, Python 3.12, pinned upstream reference | See [Matbench](matbench.md); core support does not establish extra compatibility |
| ProteinGym | Linux, Python 3.11, pinned upstream reference | See [ProteinGym](proteingym.md) |
| OpenDP | Linux, Python 3.10 and 3.12, OpenDP 0.16 | Optional bounded-mean backend; see [privacy assumptions](privacy.md#optional-opendp-backend) |
| Chemistry adapters | Linux, Python 3.11, optional RDKit | Separate split/design-audit checks |
| Untrusted script execution | Linux, Python 3.11, Docker and pinned gVisor runtime | CPU scripts in a reviewed image; Windows/macOS core support does not provide this runtime |

These environments remain separate from the cross-platform core matrix. The
[sandbox guide](sandbox.md) documents host requirements and limits; this testing
does not constitute an independent sandbox or privacy-wrapper security audit.

## Report an installation problem

Include the package version, Python version, operating system, failed command,
and a redacted error in a [bug report](https://github.com/dipeshbabu/private-lab-bench/issues/new?template=bug.yml).
Use synthetic data. Do not include private CSVs, local identifying paths, signing
keys, or credentials. State whether an optional extra was installed. Unknown
combinations remain untested until reproduced; installation success alone is not
a support claim.

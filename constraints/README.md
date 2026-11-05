# Representative core environments

`core.txt` pins the dependency environments used by the installed-distribution
compatibility matrix. Its Python markers preserve the last compatible versions
for legacy Python 3.10 and separate newer dependency floors. These constraints
apply to CI, not to the package's runtime dependency declarations.

Regenerate from the project metadata with:

```sh
uv pip compile pyproject.toml --python-version 3.10 --universal --no-header --output-file constraints/core.txt
```

Run the full compatibility matrix after updating the file. Each OS/Python job
installs both the built wheel and source archive in separate clean environments,
runs `pip check`, and records actual installed dependency versions. The smoke runs
use Python's UTF-8 mode for consistent text handling across platforms. They do
not establish support for every older dependency version permitted by the package.

The existing unconstrained Linux CI continues to exercise normal dependency
resolution and the full suite. Optional scientific extras and the gVisor runtime
retain their own jobs and documented interpreter constraints.

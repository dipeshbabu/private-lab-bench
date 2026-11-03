# Releases

PrivateLabBench uses the version in both `pyproject.toml` and `privatelabbench/__init__.py`.

## Release checklist

Before tagging:

1. CI is green on supported Python versions, package build, docs build, and Docker.
2. The version is updated consistently in `pyproject.toml`, `privatelabbench.__version__`, and `CITATION.cff`.
3. `CHANGELOG.md` describes the release.
4. `python -m build` and `python -m twine check dist/*` pass.
5. The public-release security/history audit is complete for the first public release.

Create a tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow refuses to publish if the tag version differs from package metadata.

## PyPI Trusted Publishing

The v0.1.0 release uses PyPI's OIDC-based Trusted Publishing. The publisher configuration must match:

- PyPI project: `private-lab-bench`
- repository owner: `dipeshbabu`
- repository: `private-lab-bench`
- workflow: `release.yml`
- environment: `pypi`

No long-lived PyPI API token is stored in the repository workflow.

The GitHub environment `pypi` is configured. Register the corresponding publisher on PyPI before pushing the tag. A pending publisher creates the project on its first successful upload. The workflow builds and validates distributions before publishing; verify a clean `python -m pip install private-lab-bench==0.1.0` after it succeeds. Never reuse a published version for different distribution files.

## Documentation site

The repository includes a MkDocs Material site. Build it locally with:

```bash
pip install -e '.[docs]'
mkdocs build
```

CI verifies the site builds. The documentation source is public; hosted-site deployment remains separate from the package release.

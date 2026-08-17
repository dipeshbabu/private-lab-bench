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
git tag v0.11.0
git push origin v0.11.0
```

The release workflow refuses to publish if the tag version differs from package metadata.

## PyPI Trusted Publishing

The repository is configured for PyPI's OIDC-based trusted-publishing workflow. A maintainer still needs to create/configure the matching Trusted Publisher on PyPI for:

- repository owner: `dipeshbabu`
- repository: `private-lab-bench`
- workflow: `release.yml`
- environment: `pypi`

No long-lived PyPI API token is stored in the repository workflow.

Until that external PyPI configuration and a successful release run exist, documentation should not claim that `pip install private-lab-bench` is live.

## Documentation site

The repository includes a MkDocs Material site. Build it locally with:

```bash
pip install -e '.[docs]'
mkdocs build
```

CI verifies the site builds. Hosting/deployment can be enabled once the repository is public and GitHub Pages settings are configured.

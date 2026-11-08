# Releases

PrivateLabBench uses the version in both `pyproject.toml` and `privatelabbench/__init__.py`.

## Release checklist

v0.1.7 and later are currently held by the recorded
[release prerequisites](release_readiness.md). The workflow rejects incomplete
requirements before building or uploading. Passing CI alone does not clear the
independent-audit or GPU-validation prerequisites.

Before tagging:

1. Every check on each release PR has passed. Squash merge using the checked head
   commit, then confirm CI and the full-history audit pass on the resulting main
   commit. Do not tag an untested merge.
2. Update `pyproject.toml`, `privatelabbench.__version__`, `CITATION.cff`, current
   install instructions, and the notebook together. Preserve historical release
   notes and independently versioned protocols, schemas, and dependencies.
3. Recompute unsigned example receipt integrity and regenerate signed examples
   under the new package version; never edit signed payloads without re-signing.
4. Describe the changes in `CHANGELOG.md`. Run the tests, pre-commit checks,
   strict docs build, `python -m build`, and `python -m twine check dist/*`.
5. Install both distributions in clean environments outside the checkout. Run the
   bundled packs, receipt verification, relevant regressions, and notebook using
   the installed package. Scientific integration changes also need upstream parity.

Create a tag:

```bash
git tag v0.1.6
git push origin v0.1.6
```

The release workflow refuses to publish if the tag version differs from package metadata.
It also requires successful main-branch push runs of CI, Core compatibility, and
Public Release Audit for the exact tagged SHA. Every job must pass, including the
full test matrix and combined coverage gate; missing, pending, failed, or skipped
jobs block publication. An older successful run cannot override a newer failed
run. If a tag arrives before checks finish, wait for the checks and rerun the
failed release workflow; do not move the tag.

After building, the workflow separately installs the wheel and source archive
outside the checkout and exercises the core before the upload job can start.
After PyPI publishing succeeds, it creates a GitHub Release with the same wheel,
source archive, and a `SHA256SUMS.txt` checksum file. It never rebuilds the package
between the two destinations.

## PyPI Trusted Publishing

Releases use PyPI's OIDC-based Trusted Publishing. The active publisher configuration is:

- PyPI project: `private-lab-bench`
- repository owner: `dipeshbabu`
- repository: `private-lab-bench`
- workflow: `release.yml`
- environment: `pypi`

No long-lived PyPI API token is stored in the repository workflow.

The GitHub environment `pypi` and PyPI publisher are configured. The workflow has
successfully published this project; no first-upload registration is needed.

After publishing, verify a clean
`python -m pip install private-lab-bench==0.1.6` outside the checkout. Compare the
PyPI distribution hashes, GitHub Release assets, and `SHA256SUMS.txt`. Keep the
GitHub Release title equal to the tag, such as `v0.1.6`, and edit the generated
notes to explain the changes and upgrade guidance. Confirm the README's PyPI
badge resolves to the published version. Never reuse a published version for
different distribution files; publish a new version for corrections.

## Documentation site

The repository includes a MkDocs Material site. Build it locally with:

```bash
pip install -e '.[docs]'
mkdocs build
```

CI verifies the site builds. After a successful main-branch CI run, the
Documentation deployment workflow builds that tested commit and publishes it to
[GitHub Pages](https://dipeshbabu.github.io/private-lab-bench/). Pull requests do
not deploy. Maintainers can redeploy main with the workflow's manual trigger.

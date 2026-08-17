## What changed

<!-- Keep this PR focused on one logical issue. -->

## Why

<!-- What user/research/developer problem does this solve? -->

## Related issue

Closes #

## Compatibility

- [ ] No public/schema compatibility impact
- [ ] Compatibility impact is documented and tested

Describe any change to `prediction-table/*`, `evaluation-receipt/*`, `benchmark-pack/*`, task/plugin APIs, reports, or manifests:

## Privacy / data-sharing impact

- [ ] No new row-level/private data leaves the local evaluation path
- [ ] New artifact fields/sharing behavior are documented
- [ ] Privacy wording distinguishes guarantees, empirical audits, and policy gates
- [ ] Not applicable

## Tests

<!-- Commands/checks run, including any end-to-end workflow relevant to the change. -->

```text
pytest -q
```

## Dependencies / licenses

<!-- List new dependencies/data/assets and their licenses/provenance, or state none. -->

## Checklist

- [ ] Scope is limited to this issue
- [ ] Tests added/updated
- [ ] Documentation updated when user-facing behavior changed
- [ ] Synthetic/redistributable fixtures only; no private data or credentials
- [ ] CI is expected to pass on supported Python versions

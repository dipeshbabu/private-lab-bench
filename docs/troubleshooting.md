# Troubleshooting

## `plb` is not found

Confirm the environment where PrivateLabBench was installed is active:

```bash
python -m pip show private-lab-bench
python -m pip --version
```

Both `plb` and `privatelabbench` point to the same CLI.

## Bundled packs are missing

```bash
plb list-packs
```

A normal wheel should include the community packs as package data. If a wheel install returns no packs, report the installed version and platform; CI has a clean-wheel test specifically for this regression.

## RDKit installation fails

RDKit is optional. The default prediction-table workflow and hashed molecular baseline do not require it.

```bash
pip install private-lab-bench
```

Use the RDKit extra only when you specifically need the RDKit adapter:

```bash
pip install 'private-lab-bench[rdkit]'
```

If platform-specific RDKit packaging causes problems, use a Python/environment where an RDKit wheel or conda package is available rather than making RDKit a core dependency.

## Config paths behave differently

Input paths may be absolute, relative to the working directory when they exist there, or relative to the config file. Report paths are written relative to the current working directory unless absolute paths are supplied.

Use `plb validate-config` before a long run.

## Multiclass probability errors

`prediction-table/v1` requires one probability column per declared class. Values must be finite, between 0 and 1, and each row must sum to approximately 1.

## Very small slices are absent

Configured slices below `min_slice_size` are reported as suppressed rather than receiving metrics. This is a release-safety guard, not a formal privacy guarantee.

## `mode: dp` warning

The historical `dp` spelling is deprecated. Use:

```yaml
privacy:
  mode: metric_perturbation
```

This remains heuristic perturbation with no formal DP guarantee. See [Privacy](privacy.md).

## Receipt verification fails

Run:

```bash
plb verify path/to/receipt.json
```

A hash failure means the payload changed after the integrity metadata was generated. A signature failure can also mean the wrong HMAC secret was supplied.

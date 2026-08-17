# Report Integrity and Audit Logs

PrivateLabBench JSON reports include an `integrity` block used to verify local evaluation artifacts.

It contains a canonical SHA256 payload digest and optional local HMAC signature metadata.

## Verify a report

```bash
plb verify-report reports/kinase_prediction_eval.json
```

## Run manifests

Config-driven runs write a manifest binding the config file, JSON report, Markdown report, audit log, benchmark/task identity, runner provenance, and artifact hashes.

```bash
plb verify-manifest reports/kinase_prediction_manifest.json
```

## Optional local signing

```bash
export PRIVATELABBENCH_SIGNING_SECRET="local-signing-secret"
plb run configs/prediction_eval.yaml
plb verify-manifest reports/kinase_prediction_manifest.json --signing-secret "$PRIVATELABBENCH_SIGNING_SECRET"
```

The signing key remains local. Integrity signing does not itself provide confidentiality or differential privacy.

## Config snapshot and audit log

Config-driven JSON reports record the YAML settings used for the run. Runs also write a JSONL audit event with evaluation metadata and report paths, not raw dataset rows.

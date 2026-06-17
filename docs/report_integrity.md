# Report Integrity And Audit Logs

PrivateLabBench JSON reports include an `integrity` block. This is the foundation for turning a local model evaluation into a verifiable evidence artifact.

The integrity block contains:

- `payload_sha256`: canonical SHA256 digest of the report payload excluding the integrity block itself.
- `algorithm`: currently `sha256`.
- `signed`: whether an HMAC signature was attached.
- `signature`: present only when a signing secret is configured.

## Verify a report

```bash
privatelabbench verify-report reports/kinase_prediction_eval.json
```

## Verify a run manifest

Config-driven runs also write a run manifest. The manifest binds the config file,
JSON report, Markdown report, audit log, evaluation-suite identity, runner identity, and
artifact hashes into one verification bundle. It also includes a privacy-preserving
runner attestation claim with package/runtime metadata and optional managed-runner
metadata from:

- `PRIVATELABBENCH_CODE_REVISION`
- `PRIVATELABBENCH_RUNNER_IMAGE_DIGEST`
- `PRIVATELABBENCH_ATTESTATION_ID`

```bash
privatelabbench verify-manifest reports/kinase_prediction_manifest.json
```

The manifest check recomputes artifact hashes and verifies the bound JSON report
integrity metadata.

## Evidence bundle manifest

`privatelabbench evidence` also writes an evidence manifest. The evidence manifest
binds:

- evidence JSON report
- evidence Markdown report
- source run manifest
- evidence report payload hash
- source run manifest hash

This lets a customer share one evidence bundle while preserving a verifiable chain
back to the source local evaluation.

## Create a signed report

Set `PRIVATELABBENCH_SIGNING_SECRET` in the local environment before running the config runner:

```bash
export PRIVATELABBENCH_SIGNING_SECRET="customer-local-secret"
privatelabbench run configs/prediction_eval.yaml
```

Then verify the signed report:

```bash
privatelabbench verify-report reports/kinase_prediction_eval.json --signing-secret "$PRIVATELABBENCH_SIGNING_SECRET"
privatelabbench verify-manifest reports/kinase_prediction_manifest.json --signing-secret "$PRIVATELABBENCH_SIGNING_SECRET"
```

## Config snapshot

Config-driven JSON reports include `config_snapshot`, which records the YAML settings used for the run. This makes evaluation artifacts easier to reproduce and audit.

## Audit log

Config-driven runs write a JSONL audit event after completion. The default audit path is:

```text
reports/<project>_audit.jsonl
```

A config can override this path:

```yaml
audit:
  path: reports/kinase_prediction_audit.jsonl
```

The audit event stores report paths, project name, workflow type, and privacy settings. It does not store raw dataset rows.

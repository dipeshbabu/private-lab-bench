# Report integrity and audit logs

PrivateLabBench JSON reports include an `integrity` block.

The integrity block contains:

- `payload_sha256`: canonical SHA256 digest of the report payload excluding the integrity block itself.
- `algorithm`: currently `sha256`.
- `signed`: whether an HMAC signature was attached.
- `signature`: present only when a signing secret is configured.

## Verify a report

```bash
privatelabbench verify-report reports/kinase_prediction_eval.json
```

## Create a signed report

Set `PRIVATELABBENCH_SIGNING_SECRET` in the local environment before running the config runner:

```bash
export PRIVATELABBENCH_SIGNING_SECRET="customer-local-secret"
privatelabbench run configs/prediction_eval.yaml
```

Then verify the signed report:

```bash
privatelabbench verify-report reports/kinase_prediction_eval.json --signing-secret "$PRIVATELABBENCH_SIGNING_SECRET"
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

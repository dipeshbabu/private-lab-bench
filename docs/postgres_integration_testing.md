# PostgreSQL Integration Testing

Use this when changing dashboard storage code or validating a production-like dashboard deployment path.

## Start Test PostgreSQL

```bash
docker compose -f docker-compose.test.yml up -d postgres
```

The test database listens on port `55432` by default.

```text
postgresql://privatelabbench:privatelabbench@127.0.0.1:55432/privatelabbench_test
```

Override the host port when needed:

```bash
PRIVATELABBENCH_TEST_POSTGRES_PORT=55433 docker compose -f docker-compose.test.yml up -d postgres
```

## Run Integration Tests

```bash
export PRIVATELABBENCH_TEST_POSTGRES_URL="postgresql://privatelabbench:privatelabbench@127.0.0.1:55432/privatelabbench_test"
pytest -m postgres
```

PowerShell:

```powershell
$env:PRIVATELABBENCH_TEST_POSTGRES_URL = "postgresql://privatelabbench:privatelabbench@127.0.0.1:55432/privatelabbench_test"
pytest -m postgres
```

The tests truncate `runs`, `evidence`, and `audit_events` before and after each test. Use only the disposable database from `docker-compose.test.yml`.

## Stop Test PostgreSQL

```bash
docker compose -f docker-compose.test.yml down -v
```

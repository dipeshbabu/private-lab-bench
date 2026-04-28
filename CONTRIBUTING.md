# Contributing to PrivateLabBench

PrivateLabBench is an early local-first framework for private scientific model evaluation. Contributions should keep the project simple, reproducible, and focused on secure evaluation workflows.

## Development setup

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
pip install -e .
pip install pytest
pytest -q
```

## Contribution priorities

Good first contributions include:

- new scientific dataset loaders,
- stronger molecule featurizers,
- additional evaluation metrics,
- privacy-risk scoring utilities,
- report templates,
- tests and documentation.

Please avoid adding heavyweight dependencies unless they are optional. The v0.1 package should remain installable with minimal scientific Python dependencies.

## Code style

- Keep modules small and explicit.
- Add tests for new commands or metrics.
- Prefer local-first behavior: raw data should stay on the user's machine.
- Avoid adding network calls to evaluation code unless they are clearly documented and optional.

## Privacy principle

The central design principle is simple: private scientific samples should not leave the local environment. Shared outputs should be aggregate metrics, privacy-preserving summaries, or explicit user-approved reports.

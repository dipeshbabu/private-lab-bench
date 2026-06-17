from __future__ import annotations

from html import escape
import json
import os
import time
from typing import Any
from urllib.parse import urlencode

try:
    from fastapi import Depends, FastAPI, HTTPException, Request, status
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Dashboard API dependencies are missing. Install with: pip install -e '.[api]'") from exc

from privatelabbench import __version__
from privatelabbench.dashboard.auth import require_dashboard_api_key, require_dashboard_api_key_for_org
from privatelabbench.dashboard.schemas import (
    AuditEvent,
    BenchmarkRun,
    EvidenceRecord,
    LeaderboardEntry,
    SanitizedEvidencePayload,
    SanitizedRunPayload,
)
from privatelabbench.dashboard.store import create_dashboard_store
from privatelabbench.signing import verification_result


DASHBOARD_RATE_LIMIT_ENV = "PRIVATELABBENCH_DASHBOARD_RATE_LIMIT_PER_MINUTE"
AUDIT_RETENTION_DAYS_ENV = "PRIVATELABBENCH_AUDIT_RETENTION_DAYS"
PRIVATE_METADATA_KEYS = {
    "dataset_path",
    "directory",
    "target",
    "target_column",
    "prediction_column",
    "split_column",
    "prediction_summary",
    "clients",
    "shift",
    "error_slices",
}
_RATE_LIMIT_BUCKETS: dict[str, list[float]] = {}


def get_store() -> Any:
    store = create_dashboard_store()
    retention_days = _audit_retention_days()
    if retention_days:
        store.prune_audit_events(retention_days)
    return store


def _audit_retention_days() -> int:
    raw = os.getenv(AUDIT_RETENTION_DAYS_ENV, "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _dashboard_rate_limit() -> int:
    raw = os.getenv(DASHBOARD_RATE_LIMIT_ENV, "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _rate_limit_key(request: Request) -> str:
    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if provided:
        return f"api-key:{provided}"
    if request.client and request.client.host:
        return f"client:{request.client.host}"
    return "client:unknown"


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.4g}"
    if value is None:
        return ""
    return str(value)


def _render_metrics(metrics: dict[str, float]) -> str:
    if not metrics:
        return '<span class="muted">No metrics</span>'
    items = [
        f'<span class="metric"><span>{escape(str(key))}</span><strong>{escape(_format_value(value))}</strong></span>'
        for key, value in sorted(metrics.items())
    ]
    return "".join(items)


def _render_artifacts(run: BenchmarkRun) -> str:
    if not run.artifacts:
        return '<span class="muted">None</span>'
    return ", ".join(escape(f"{artifact.name} ({artifact.kind})") for artifact in run.artifacts)


def _dashboard_query(api_key: str | None = None, **params: Any) -> str:
    query = {key: value for key, value in params.items() if value not in (None, "")}
    if api_key:
        query["api_key"] = api_key
    return f"?{urlencode(query)}" if query else ""


def _render_shell(title: str, body: str, eyebrow: str = "Sanitized evaluation evidence only") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --border: #d7dde5;
      --bg: #f6f8fa;
      --text: #18202a;
      --muted: #647181;
      --accent: #126f63;
      --accent-dark: #0d5f55;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      background: var(--bg);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.45;
    }}
    header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      padding: 24px 28px 18px;
      border-bottom: 1px solid var(--border);
      background: #ffffff;
    }}
    h1 {{ margin: 0; font-size: 22px; font-weight: 650; }}
    h2 {{ margin: 0 0 12px; font-size: 15px; font-weight: 650; }}
    .meta {{ color: var(--muted); font-size: 13px; }}
    main {{ padding: 22px 28px 30px; }}
    form {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 16px;
    }}
    input {{
      width: min(320px, 100%);
      height: 34px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0 10px;
      background: #ffffff;
      color: var(--text);
    }}
    input[type="checkbox"] {{ width: auto; height: auto; }}
    label {{ display: inline-flex; align-items: center; gap: 6px; color: var(--muted); }}
    button, .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      height: 34px;
      border: 1px solid var(--accent-dark);
      border-radius: 6px;
      padding: 0 12px;
      background: var(--accent);
      color: #ffffff;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
    }}
    a {{ color: var(--accent-dark); }}
    .table-wrap, .panel {{
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #ffffff;
    }}
    .panel {{ padding: 16px; overflow-x: visible; }}
    .stack {{ display: grid; gap: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1040px; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ color: #415062; background: #fbfcfd; font-size: 12px; text-transform: uppercase; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; word-break: break-word; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
    }}
    dl {{ display: grid; grid-template-columns: minmax(120px, 180px) 1fr; gap: 8px 12px; margin: 0; }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; min-width: 0; }}
    .metric {{
      display: inline-flex;
      gap: 6px;
      align-items: baseline;
      margin: 0 8px 6px 0;
      white-space: nowrap;
    }}
    .metric span, .muted {{ color: var(--muted); }}
    .empty {{ color: var(--muted); text-align: center; padding: 28px 12px; }}
    @media (max-width: 720px) {{
      header {{ display: block; padding: 18px; }}
      main {{ padding: 16px; }}
      h1 {{ font-size: 19px; }}
      dl {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>{escape(title)}</h1>
      <div class="meta">{escape(eyebrow)}</div>
    </div>
    <div class="meta">Version {escape(__version__)}</div>
  </header>
  <main>{body}</main>
</body>
</html>"""


def _render_dashboard(
    runs: list[BenchmarkRun],
    project: str | None,
    benchmark_id: str | None,
    limit: int,
    api_key: str | None = None,
) -> str:
    rows = []
    for run in runs:
        sample_count = run.total_samples or run.n_samples or ""
        benchmark = run.benchmark_id or ""
        if run.benchmark_version:
            benchmark = f"{benchmark}@{run.benchmark_version}" if benchmark else run.benchmark_version
        detail_url = f"/runs/{escape(run.id)}{_dashboard_query(api_key=api_key)}"
        rows.append(
            "<tr>"
            f'<td><a href="{detail_url}"><code>{escape(run.id)}</code></a></td>'
            f"<td>{escape(benchmark)}</td>"
            f"<td>{escape(run.project)}</td>"
            f"<td>{escape(run.workflow)}</td>"
            f"<td>{escape(run.task_type or '')}</td>"
            f"<td>{escape(_format_value(sample_count))}</td>"
            f"<td>{_render_metrics(run.metrics)}</td>"
            f"<td>{escape(_format_value(run.privacy.get('mode') or run.privacy.get('summary')))}</td>"
            f"<td>{_render_artifacts(run)}</td>"
            f"<td>{escape(run.created_at)}</td>"
            "</tr>"
        )

    body = (
        "\n".join(rows)
        if rows
        else '<tr><td colspan="10" class="empty">No synced runs found.</td></tr>'
    )
    project_value = escape(project or "")
    benchmark_value = escape(benchmark_id or "")
    hidden_api_key = f'<input type="hidden" name="api_key" value="{escape(api_key)}">' if api_key else ""
    content = f"""
    <form method="get" action="/">
      {hidden_api_key}
      <input name="project" value="{project_value}" placeholder="Filter by project">
      <input name="benchmark_id" value="{benchmark_value}" placeholder="Filter by evaluation suite">
      <button type="submit">Filter</button>
    </form>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Evaluation Suite</th>
            <th>Project</th>
            <th>Workflow</th>
            <th>Task</th>
            <th>Samples</th>
            <th>Metrics</th>
            <th>Privacy</th>
            <th>Artifacts</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
"""
    return _render_shell(
        "PrivateLabBench Dashboard",
        content,
        eyebrow=f"Sanitized evaluation evidence only | Showing {len(runs)} of {limit}",
    )


def _render_evidence_dashboard(
    evidence: list[EvidenceRecord],
    project: str | None,
    recommendation: str | None,
    limit: int,
    api_key: str | None = None,
) -> str:
    rows = []
    for item in evidence:
        detail_url = f"/evidence/{escape(item.id)}{_dashboard_query(api_key=api_key)}"
        lift = "" if item.relative_lift is None else _format_value(item.relative_lift)
        rows.append(
            "<tr>"
            f'<td><a href="{detail_url}"><code>{escape(item.id)}</code></a></td>'
            f"<td>{escape(item.project)}</td>"
            f"<td>{escape(item.recommendation)}</td>"
            f"<td>{escape(item.decision_metric)}</td>"
            f"<td>{escape(lift)}</td>"
            f"<td>{escape(_format_value(item.privacy.get('gate_status')))}</td>"
            f"<td>{escape(_format_value(item.verification.get('manifest_valid')))}</td>"
            f"<td>{escape(item.claim)}</td>"
            f"<td>{escape(item.created_at)}</td>"
            "</tr>"
        )

    body = "\n".join(rows) if rows else '<tr><td colspan="9" class="empty">No synced evidence found.</td></tr>'
    project_value = escape(project or "")
    recommendation_value = escape(recommendation or "")
    hidden_api_key = f'<input type="hidden" name="api_key" value="{escape(api_key)}">' if api_key else ""
    content = f"""
    <form method="get" action="/evidence">
      {hidden_api_key}
      <input name="project" value="{project_value}" placeholder="Filter by project">
      <input name="recommendation" value="{recommendation_value}" placeholder="go, no-go, needs-review">
      <button type="submit">Filter</button>
    </form>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Evidence</th>
            <th>Project</th>
            <th>Recommendation</th>
            <th>Metric</th>
            <th>Relative Lift</th>
            <th>Privacy Gate</th>
            <th>Manifest Valid</th>
            <th>Claim</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
"""
    return _render_shell(
        "PrivateLabBench Evidence",
        content,
        eyebrow=f"Sanitized model-claim evidence only | Showing {len(evidence)} of {limit}",
    )


def _render_definition_list(items: list[tuple[str, Any]]) -> str:
    rows = []
    for key, value in items:
        if value in (None, ""):
            continue
        rows.append(f"<dt>{escape(key)}</dt><dd>{escape(_format_value(value))}</dd>")
    return f"<dl>{''.join(rows)}</dl>" if rows else '<span class="muted">None</span>'


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in metadata.items()
        if str(key) not in PRIVATE_METADATA_KEYS and isinstance(value, (str, int, float, bool, type(None)))
    }


def _render_json_block(value: Any) -> str:
    if not value:
        return '<span class="muted">None</span>'
    return f"<pre>{escape(json.dumps(value, indent=2, sort_keys=True))}</pre>"


def _render_artifact_table(run: BenchmarkRun) -> str:
    if not run.artifacts:
        return '<span class="muted">None</span>'
    rows = []
    for artifact in run.artifacts:
        rows.append(
            "<tr>"
            f"<td>{escape(artifact.name)}</td>"
            f"<td>{escape(artifact.kind)}</td>"
            f"<td><code>{escape(artifact.sha256 or '')}</code></td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Name</th><th>Kind</th><th>SHA256</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_evidence_artifact_table(evidence: EvidenceRecord) -> str:
    if not evidence.artifacts:
        return '<span class="muted">None</span>'
    rows = []
    for artifact in evidence.artifacts:
        rows.append(
            "<tr>"
            f"<td>{escape(artifact.name)}</td>"
            f"<td>{escape(artifact.kind)}</td>"
            f"<td><code>{escape(artifact.sha256 or '')}</code></td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Name</th><th>Kind</th><th>SHA256</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_audit_events(events: list[AuditEvent]) -> str:
    if not events:
        return '<span class="muted">None</span>'
    rows = []
    for event in events:
        rows.append(
            "<tr>"
            f"<td><code>{escape(event.id)}</code></td>"
            f"<td>{escape(event.event_type)}</td>"
            f"<td>{escape(event.created_at)}</td>"
            f"<td>{_render_json_block(event.payload)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Event</th><th>Type</th><th>Created</th><th>Payload</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_run_detail(run: BenchmarkRun, events: list[AuditEvent], api_key: str | None = None) -> str:
    overview = _render_definition_list(
        [
            ("Run ID", run.id),
            ("Source run ID", run.source_run_id),
            ("Organization", run.organization_id),
            ("Benchmark", run.benchmark_id),
            ("Benchmark version", run.benchmark_version),
            ("Benchmark suite", run.benchmark_suite),
            ("Domain", run.domain),
            ("Project", run.project),
            ("Workflow", run.workflow),
            ("Status", run.status),
            ("Task", run.task_type),
            ("Samples", run.n_samples),
            ("Clients", run.n_clients),
            ("Total samples", run.total_samples),
            ("Sync runner", run.sync_runner_id),
            ("Signature verified", run.signature_verified),
            ("Signature algorithm", run.signature_algorithm),
            ("Signed payload SHA256", run.signed_payload_sha256),
            ("Created", run.created_at),
        ]
    )
    back_url = f"/{_dashboard_query(api_key=api_key)}"
    safe_metadata = _safe_metadata(run.metadata)
    content = f"""
    <div class="stack">
      <div><a class="button" href="{back_url}">Back to runs</a></div>
      <section class="panel">
        <h2>Overview</h2>
        {overview}
      </section>
      <section class="panel">
        <h2>Metrics</h2>
        {_render_metrics(run.metrics)}
      </section>
      <section class="panel">
        <h2>Privacy</h2>
        {_render_json_block(run.privacy)}
      </section>
      <section class="panel">
        <h2>Artifacts</h2>
        {_render_artifact_table(run)}
      </section>
      <section class="panel">
        <h2>Sanitized Metadata</h2>
        {_render_json_block(safe_metadata)}
      </section>
      <section class="panel">
        <h2>Audit Events</h2>
        {_render_audit_events(events)}
      </section>
    </div>
"""
    return _render_shell(f"Run {run.id}", content, eyebrow="Sanitized run detail")


def _render_evidence_detail(evidence: EvidenceRecord, events: list[AuditEvent], api_key: str | None = None) -> str:
    overview = _render_definition_list(
        [
            ("Evidence ID", evidence.id),
            ("Source run ID", evidence.source_run_id),
            ("Source evidence ID", evidence.source_evidence_id),
            ("Organization", evidence.organization_id),
            ("Project", evidence.project),
            ("Benchmark", evidence.benchmark_id),
            ("Benchmark version", evidence.benchmark_version),
            ("Benchmark suite", evidence.benchmark_suite),
            ("Recommendation", evidence.recommendation),
            ("Decision status", evidence.decision_status),
            ("Decision metric", evidence.decision_metric),
            ("Direction", evidence.direction),
            ("Minimum lift", evidence.minimum_lift),
            ("Candidate value", evidence.candidate_value),
            ("Baseline value", evidence.baseline_value),
            ("Absolute delta", evidence.absolute_delta),
            ("Relative lift", evidence.relative_lift),
            ("Sync runner", evidence.sync_runner_id),
            ("Signature verified", evidence.signature_verified),
            ("Signed payload SHA256", evidence.signed_payload_sha256),
            ("Created", evidence.created_at),
        ]
    )
    back_url = f"/evidence{_dashboard_query(api_key=api_key)}"
    safe_metadata = _safe_metadata(evidence.metadata)
    content = f"""
    <div class="stack">
      <div><a class="button" href="{back_url}">Back to evidence</a></div>
      <section class="panel">
        <h2>Claim</h2>
        <p>{escape(evidence.claim)}</p>
      </section>
      <section class="panel">
        <h2>Overview</h2>
        {overview}
      </section>
      <section class="panel">
        <h2>Privacy</h2>
        {_render_json_block(evidence.privacy)}
      </section>
      <section class="panel">
        <h2>Verification</h2>
        {_render_json_block(evidence.verification)}
      </section>
      <section class="panel">
        <h2>Artifacts</h2>
        {_render_evidence_artifact_table(evidence)}
      </section>
      <section class="panel">
        <h2>Sanitized Metadata</h2>
        {_render_json_block(safe_metadata)}
      </section>
      <section class="panel">
        <h2>Audit Events</h2>
        {_render_audit_events(events)}
      </section>
    </div>
"""
    return _render_shell(f"Evidence {evidence.id}", content, eyebrow="Sanitized model-claim evidence detail")


def _render_leaderboard(
    entries: list[LeaderboardEntry],
    *,
    benchmark_id: str,
    metric: str,
    order: str,
    require_publishable: bool,
    api_key: str | None = None,
) -> str:
    rows = []
    for entry in entries:
        detail_url = f"/runs/{escape(entry.run_id)}{_dashboard_query(api_key=api_key)}"
        rows.append(
            "<tr>"
            f"<td>{entry.rank}</td>"
            f'<td><a href="{detail_url}"><code>{escape(entry.run_id)}</code></a></td>'
            f"<td>{escape(entry.project)}</td>"
            f"<td>{escape(entry.organization_id)}</td>"
            f"<td>{escape(_format_value(entry.value))}</td>"
            f"<td>{escape(_format_value(entry.samples))}</td>"
            f"<td>{escape(_format_value(entry.metadata.get('privacy_gate_status')))}</td>"
            f"<td>{escape(entry.created_at)}</td>"
            "</tr>"
        )
    body = (
        "\n".join(rows)
        if rows
        else '<tr><td colspan="8" class="empty">No eligible sanitized runs found.</td></tr>'
    )
    hidden_api_key = f'<input type="hidden" name="api_key" value="{escape(api_key)}">' if api_key else ""
    checked = "checked" if require_publishable else ""
    content = f"""
    <form method="get" action="/leaderboards/{escape(benchmark_id)}">
      {hidden_api_key}
      <input name="metric" value="{escape(metric)}" placeholder="Metric">
      <input name="order" value="{escape(order)}" placeholder="asc or desc">
      <label><input type="checkbox" name="require_publishable" value="true" {checked}> Publishable only</label>
      <button type="submit">Update</button>
    </form>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Run</th>
            <th>Project</th>
            <th>Organization</th>
            <th>{escape(metric)}</th>
            <th>Samples</th>
            <th>Privacy Gate</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
"""
    return _render_shell(
        f"Leaderboard {benchmark_id}",
        content,
        eyebrow=f"Sanitized leaderboard | metric={metric} | order={order}",
    )


app = FastAPI(
    title="PrivateLabBench Dashboard API",
    version=__version__,
    description="Evidence dashboard API for sanitized private scientific AI evaluation results.",
)


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    if request.url.path in {"/health", "/ready", "/metrics"}:
        return await call_next(request)
    limit = _dashboard_rate_limit()
    if limit <= 0:
        return await call_next(request)

    now = time.monotonic()
    window_start = now - 60
    key = _rate_limit_key(request)
    bucket = [timestamp for timestamp in _RATE_LIMIT_BUCKETS.get(key, []) if timestamp >= window_start]
    if len(bucket) >= limit:
        _RATE_LIMIT_BUCKETS[key] = bucket
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Dashboard API rate limit exceeded."},
            headers={"Retry-After": "60"},
        )
    bucket.append(now)
    _RATE_LIMIT_BUCKETS[key] = bucket
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "privatelabbench-dashboard", "version": __version__}


@app.get("/ready")
def ready() -> dict[str, object]:
    try:
        store = get_store()
        return {
            "status": "ready",
            "service": "privatelabbench-dashboard",
            "version": __version__,
            "database": str(store.path),
            "counts": store.counts(),
        }
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    counts = get_store().counts()
    lines = [
        "# HELP privatelabbench_dashboard_runs Sanitized benchmark runs stored.",
        "# TYPE privatelabbench_dashboard_runs gauge",
        f"privatelabbench_dashboard_runs {counts['runs']}",
        "# HELP privatelabbench_dashboard_evidence Model claim evidence records stored.",
        "# TYPE privatelabbench_dashboard_evidence gauge",
        f"privatelabbench_dashboard_evidence {counts['evidence']}",
        "# HELP privatelabbench_dashboard_audit_events Audit events stored.",
        "# TYPE privatelabbench_dashboard_audit_events gauge",
        f"privatelabbench_dashboard_audit_events {counts['audit_events']}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_api_key)])
def dashboard_home(
    project: str | None = None,
    benchmark_id: str | None = None,
    limit: int = 50,
    api_key: str | None = None,
) -> HTMLResponse:
    runs = get_store().list_runs(project=project, benchmark_id=benchmark_id, limit=limit)
    return HTMLResponse(
        _render_dashboard(
            runs,
            project=project,
            benchmark_id=benchmark_id,
            limit=max(1, min(limit, 200)),
            api_key=api_key,
        )
    )


@app.get("/evidence", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_api_key)])
def dashboard_evidence_home(
    project: str | None = None,
    recommendation: str | None = None,
    limit: int = 50,
    api_key: str | None = None,
) -> HTMLResponse:
    evidence = get_store().list_evidence(project=project, recommendation=recommendation, limit=limit)
    return HTMLResponse(
        _render_evidence_dashboard(
            evidence,
            project=project,
            recommendation=recommendation,
            limit=max(1, min(limit, 200)),
            api_key=api_key,
        )
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_api_key)])
def dashboard_run_detail(run_id: str, api_key: str | None = None) -> HTMLResponse:
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown run_id: {run_id}")
    events = [
        event
        for event in store.list_audit_events(organization_id=run.organization_id, limit=200)
        if event.payload.get("run_id") == run.id
    ]
    return HTMLResponse(_render_run_detail(run, events, api_key=api_key))


@app.get("/evidence/{evidence_id}", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_api_key)])
def dashboard_evidence_detail(evidence_id: str, api_key: str | None = None) -> HTMLResponse:
    store = get_store()
    evidence = store.get_evidence(evidence_id)
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown evidence_id: {evidence_id}")
    events = [
        event
        for event in store.list_audit_events(organization_id=evidence.organization_id, limit=200)
        if event.payload.get("evidence_id") == evidence.id
    ]
    return HTMLResponse(_render_evidence_detail(evidence, events, api_key=api_key))


@app.get("/leaderboards/{benchmark_id}", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_api_key)])
def dashboard_leaderboard(
    benchmark_id: str,
    metric: str,
    order: str = "asc",
    require_publishable: bool = True,
    limit: int = 50,
    api_key: str | None = None,
) -> HTMLResponse:
    entries = get_store().leaderboard(
        benchmark_id=benchmark_id,
        metric=metric,
        order=order,
        require_publishable=require_publishable,
        limit=limit,
    )
    return HTMLResponse(
        _render_leaderboard(
            entries,
            benchmark_id=benchmark_id,
            metric=metric,
            order=order,
            require_publishable=require_publishable,
            api_key=api_key,
        )
    )


@app.post("/v1/runs", response_model=BenchmarkRun, dependencies=[Depends(require_dashboard_api_key)])
async def sync_run(request: Request) -> BenchmarkRun:
    body = await request.body()
    signature = verification_result(payload=body, headers=request.headers)
    if signature.get("required") and not signature.get("verified"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Runner signature verification failed: {signature.get('reason')}",
        )
    payload = SanitizedRunPayload.model_validate_json(body)
    require_dashboard_api_key_for_org(
        payload.organization_id,
        x_api_key=request.headers.get("x-api-key"),
        api_key=request.query_params.get("api_key"),
    )
    return get_store().create_run(payload, signature=signature)


@app.post("/v1/evidence", response_model=EvidenceRecord, dependencies=[Depends(require_dashboard_api_key)])
async def sync_evidence(request: Request) -> EvidenceRecord:
    body = await request.body()
    signature = verification_result(payload=body, headers=request.headers)
    if signature.get("required") and not signature.get("verified"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Runner signature verification failed: {signature.get('reason')}",
        )
    payload = SanitizedEvidencePayload.model_validate_json(body)
    require_dashboard_api_key_for_org(
        payload.organization_id,
        x_api_key=request.headers.get("x-api-key"),
        api_key=request.query_params.get("api_key"),
    )
    return get_store().create_evidence(payload, signature=signature)


@app.get("/v1/runs", response_model=list[BenchmarkRun], dependencies=[Depends(require_dashboard_api_key)])
def list_runs(project: str | None = None, benchmark_id: str | None = None, limit: int = 50) -> list[BenchmarkRun]:
    return get_store().list_runs(project=project, benchmark_id=benchmark_id, limit=limit)


@app.get("/v1/evidence", response_model=list[EvidenceRecord], dependencies=[Depends(require_dashboard_api_key)])
def list_evidence(
    project: str | None = None,
    recommendation: str | None = None,
    limit: int = 50,
) -> list[EvidenceRecord]:
    return get_store().list_evidence(project=project, recommendation=recommendation, limit=limit)


@app.get("/v1/runs/{run_id}", response_model=BenchmarkRun, dependencies=[Depends(require_dashboard_api_key)])
def get_run(run_id: str) -> BenchmarkRun:
    run = get_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown run_id: {run_id}")
    return run


@app.get("/v1/evidence/{evidence_id}", response_model=EvidenceRecord, dependencies=[Depends(require_dashboard_api_key)])
def get_evidence(evidence_id: str) -> EvidenceRecord:
    evidence = get_store().get_evidence(evidence_id)
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown evidence_id: {evidence_id}")
    return evidence


@app.get("/v1/leaderboards/{benchmark_id}", response_model=list[LeaderboardEntry], dependencies=[Depends(require_dashboard_api_key)])
def get_leaderboard(
    benchmark_id: str,
    metric: str,
    order: str = "asc",
    require_publishable: bool = True,
    limit: int = 50,
) -> list[LeaderboardEntry]:
    return get_store().leaderboard(
        benchmark_id=benchmark_id,
        metric=metric,
        order=order,
        require_publishable=require_publishable,
        limit=limit,
    )


@app.get("/v1/audit-events", response_model=list[AuditEvent], dependencies=[Depends(require_dashboard_api_key)])
def list_audit_events(organization_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
    return get_store().list_audit_events(organization_id=organization_id, limit=limit)

from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

try:
    from fastapi import Depends, FastAPI, HTTPException, status
    from fastapi.responses import HTMLResponse
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Dashboard API dependencies are missing. Install with: pip install -e '.[api]'") from exc

from privatelabbench import __version__
from privatelabbench.dashboard.auth import require_dashboard_api_key
from privatelabbench.dashboard.schemas import AuditEvent, BenchmarkRun, SanitizedRunPayload
from privatelabbench.dashboard.store import DashboardStore


DASHBOARD_DB_ENV = "PRIVATELABBENCH_DASHBOARD_DB"
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


def get_store() -> DashboardStore:
    return DashboardStore(Path(os.getenv(DASHBOARD_DB_ENV, ".privatelabbench_dashboard/dashboard.db")))


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


def _render_shell(title: str, body: str, eyebrow: str = "Sanitized benchmark runs only") -> str:
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


def _render_dashboard(runs: list[BenchmarkRun], project: str | None, limit: int, api_key: str | None = None) -> str:
    rows = []
    for run in runs:
        sample_count = run.total_samples or run.n_samples or ""
        detail_url = f"/runs/{escape(run.id)}{_dashboard_query(api_key=api_key)}"
        rows.append(
            "<tr>"
            f'<td><a href="{detail_url}"><code>{escape(run.id)}</code></a></td>'
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
        else '<tr><td colspan="9" class="empty">No synced runs found.</td></tr>'
    )
    project_value = escape(project or "")
    hidden_api_key = f'<input type="hidden" name="api_key" value="{escape(api_key)}">' if api_key else ""
    content = f"""
    <form method="get" action="/">
      {hidden_api_key}
      <input name="project" value="{project_value}" placeholder="Filter by project">
      <button type="submit">Filter</button>
    </form>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Run</th>
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
        eyebrow=f"Sanitized benchmark runs only | Showing {len(runs)} of {limit}",
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
            ("Organization", run.organization_id),
            ("Project", run.project),
            ("Workflow", run.workflow),
            ("Status", run.status),
            ("Task", run.task_type),
            ("Samples", run.n_samples),
            ("Clients", run.n_clients),
            ("Total samples", run.total_samples),
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


app = FastAPI(
    title="PrivateLabBench Dashboard API",
    version=__version__,
    description="Hosted-dashboard API for sanitized scientific-model benchmark results.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "privatelabbench-dashboard", "version": __version__}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_api_key)])
def dashboard_home(project: str | None = None, limit: int = 50, api_key: str | None = None) -> HTMLResponse:
    runs = get_store().list_runs(project=project, limit=limit)
    return HTMLResponse(_render_dashboard(runs, project=project, limit=max(1, min(limit, 200)), api_key=api_key))


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


@app.post("/v1/runs", response_model=BenchmarkRun, dependencies=[Depends(require_dashboard_api_key)])
def sync_run(payload: SanitizedRunPayload) -> BenchmarkRun:
    return get_store().create_run(payload)


@app.get("/v1/runs", response_model=list[BenchmarkRun], dependencies=[Depends(require_dashboard_api_key)])
def list_runs(project: str | None = None, limit: int = 50) -> list[BenchmarkRun]:
    return get_store().list_runs(project=project, limit=limit)


@app.get("/v1/runs/{run_id}", response_model=BenchmarkRun, dependencies=[Depends(require_dashboard_api_key)])
def get_run(run_id: str) -> BenchmarkRun:
    run = get_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown run_id: {run_id}")
    return run


@app.get("/v1/audit-events", response_model=list[AuditEvent], dependencies=[Depends(require_dashboard_api_key)])
def list_audit_events(organization_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
    return get_store().list_audit_events(organization_id=organization_id, limit=limit)

from __future__ import annotations

from html import escape
import os
from pathlib import Path
from typing import Any

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


def _render_dashboard(runs: list[BenchmarkRun], project: str | None, limit: int) -> str:
    rows = []
    for run in runs:
        sample_count = run.total_samples or run.n_samples or ""
        rows.append(
            "<tr>"
            f"<td><code>{escape(run.id)}</code></td>"
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
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PrivateLabBench Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --border: #d7dde5;
      --bg: #f6f8fa;
      --text: #18202a;
      --muted: #647181;
      --accent: #126f63;
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
    button {{
      height: 34px;
      border: 1px solid #0d5f55;
      border-radius: 6px;
      padding: 0 12px;
      background: var(--accent);
      color: #ffffff;
      font-weight: 600;
      cursor: pointer;
    }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #ffffff;
    }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1040px; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ color: #415062; background: #fbfcfd; font-size: 12px; text-transform: uppercase; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }}
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
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>PrivateLabBench Dashboard</h1>
      <div class="meta">Sanitized benchmark runs only</div>
    </div>
    <div class="meta">Version {escape(__version__)} | Showing {len(runs)} of {limit}</div>
  </header>
  <main>
    <form method="get" action="/">
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
  </main>
</body>
</html>"""


app = FastAPI(
    title="PrivateLabBench Dashboard API",
    version=__version__,
    description="Hosted-dashboard API for sanitized scientific-model benchmark results.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "privatelabbench-dashboard", "version": __version__}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_api_key)])
def dashboard_home(project: str | None = None, limit: int = 50) -> HTMLResponse:
    runs = get_store().list_runs(project=project, limit=limit)
    return HTMLResponse(_render_dashboard(runs, project=project, limit=max(1, min(limit, 200))))


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

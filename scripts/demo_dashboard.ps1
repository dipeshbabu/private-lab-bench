param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8010,
    [string]$ApiKey = "dashboard-secret",
    [string]$OrganizationId = "demo-customer",
    [string]$ConfigPath = "configs/prediction_eval.yaml",
    [switch]$OpenDashboard
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$env:PRIVATELABBENCH_DASHBOARD_API_KEY = $ApiKey
$BaseUrl = "http://${HostName}:$Port"
$DashboardUrl = "$BaseUrl/?api_key=$ApiKey"

function Test-DashboardReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/health" -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

if (-not (Test-DashboardReady)) {
    Write-Host "Starting PrivateLabBench dashboard on $BaseUrl ..."
    Start-Process `
        -WindowStyle Hidden `
        -FilePath "python" `
        -ArgumentList @(
            "-m",
            "privatelabbench.cli",
            "serve-dashboard",
            "--host",
            $HostName,
            "--port",
            "$Port"
        ) `
        -WorkingDirectory $RepoRoot

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-DashboardReady) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw "Dashboard did not become ready at $BaseUrl"
    }
}
else {
    Write-Host "Dashboard is already running on $BaseUrl."
}

Write-Host "Syncing sanitized demo run from $ConfigPath ..."
python -m privatelabbench.cli sync-dashboard $ConfigPath `
    --endpoint $BaseUrl `
    --api-key $ApiKey `
    --organization-id $OrganizationId

Write-Host ""
Write-Host "Dashboard demo is ready:"
Write-Host $DashboardUrl
Write-Host ""
Write-Host "Local reports are under: $RepoRoot\reports"

if ($OpenDashboard) {
    Start-Process $DashboardUrl
}

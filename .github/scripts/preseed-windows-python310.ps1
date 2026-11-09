#requires -Version 7.0

$ErrorActionPreference = 'Stop'

# The upstream installer changes the toolcache and registry. Never run it locally
# or on a persistent/self-hosted runner.
if (-not $IsWindows -or -not [Environment]::Is64BitProcess -or
    $env:GITHUB_ACTIONS -ne 'true' -or
    $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or
    $env:RUNNER_OS -ne 'Windows' -or $env:RUNNER_ARCH -ne 'X64') {
    throw 'Python preseed is restricted to GitHub-hosted Windows X64 runners.'
}
if ([string]::IsNullOrWhiteSpace($env:PLB_GITHUB_API_TOKEN)) {
    throw 'The step-scoped GitHub API token is required.'
}

foreach ($name in @('RUNNER_TOOL_CACHE', 'RUNNER_TEMP')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value) -or
        -not [IO.Path]::IsPathFullyQualified($value) -or
        -not (Test-Path -LiteralPath $value -PathType Container)) {
        throw "A valid $name directory is required."
    }
}

$toolcacheRoot = [IO.Path]::GetFullPath($env:RUNNER_TOOL_CACHE).TrimEnd('\', '/')
# setup.ps1 prefers AGENT_TOOLSDIRECTORY when set; it must target the cache that
# setup-python subsequently reads.
if (-not [string]::IsNullOrEmpty($env:AGENT_TOOLSDIRECTORY) -and
    [IO.Path]::GetFullPath($env:AGENT_TOOLSDIRECTORY).TrimEnd('\', '/') -ne $toolcacheRoot) {
    throw 'AGENT_TOOLSDIRECTORY must match RUNNER_TOOL_CACHE.'
}

$pythonDirectory = Join-Path $toolcacheRoot 'Python/3.10.11/x64'
$pythonExecutable = Join-Path $pythonDirectory 'python.exe'
$complete = "$pythonDirectory.complete"
if ((Test-Path -LiteralPath $complete -PathType Leaf) -and
    (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    Write-Host 'Python 3.10.11 x64 is already cached; setup-python will select it.'
    return
}

# The release-download URL persistently returns HTTP 504. Fetch the identical
# official asset through the API, pinned to the release's hashes.sha256 value:
# https://github.com/actions/python-versions/releases/tag/3.10.11-11114431484
# https://api.github.com/repos/actions/python-versions/releases/assets/195976308
$expectedSha256 = 'c7c029492644331f01facb97382d1f145882b162d920f6b58b297af22bf459c4'
$downloadDirectory = Join-Path $env:RUNNER_TEMP ("plb-python-3.10.11-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $downloadDirectory | Out-Null
$archive = Join-Path $downloadDirectory 'python-3.10.11-win32-x64.zip'
& curl.exe --fail --location --retry 3 --silent --show-error `
    --connect-timeout 30 --max-time 180 `
    --header 'Accept: application/octet-stream' `
    --header "Authorization: Bearer $env:PLB_GITHUB_API_TOKEN" `
    'https://api.github.com/repos/actions/python-versions/releases/assets/195976320' `
    --output $archive
if ($LASTEXITCODE -ne 0) { throw 'Official Python archive download failed.' }
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedSha256) {
    throw 'Official Python archive SHA256 mismatch; installation refused.'
}

$extracted = Join-Path $downloadDirectory 'extracted'
[IO.Compression.ZipFile]::ExtractToDirectory($archive, $extracted)

# Match setup-python v7.1.0's installPython invocation: the archive's unchanged
# setup.ps1 runs under Windows PowerShell from the extracted working directory.
# It installs Python and writes x64.complete; do not fabricate a cache marker.
# https://github.com/actions/setup-python/blob/v7.1.0/src/install-python.ts
Push-Location -LiteralPath $extracted
try {
    & powershell.exe ./setup.ps1
    if ($LASTEXITCODE -ne 0) { throw 'Official Python setup.ps1 failed.' }
} finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath $complete -PathType Leaf) -or
    -not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw 'Official Python installer did not complete the expected toolcache entry.'
}

# Leave PATH/environment selection to the following setup-python action.
& $pythonExecutable -c "import struct, sys; assert sys.version_info[:3] == (3, 10, 11); assert struct.calcsize('P') == 8"
if ($LASTEXITCODE -ne 0) { throw 'The cached Python is not CPython 3.10.11 x64.' }

$ErrorActionPreference = "Stop"

$workerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path -LiteralPath (Join-Path $workerRoot "..\..")
$preflight = Join-Path $workerRoot "build_preflight.py"
$pythonCandidates = @()

if ($env:DATA_AUTOMATION_WORKER_PYTHON) {
  $pythonCandidates += $env:DATA_AUTOMATION_WORKER_PYTHON
} else {
  try {
    foreach ($line in (& py -0p 2>$null)) {
      if ($line -match "([A-Za-z]:\\.*python\.exe)\s*$") { $pythonCandidates += $Matches[1].Trim() }
    }
  } catch {}
  foreach ($selector in @("-3.12-64", "-V:3.12-x64", "-3.12")) {
    try {
      $candidate = (& py $selector -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
      if ($LASTEXITCODE -eq 0 -and $candidate) { $pythonCandidates += $candidate.Trim() }
    } catch {}
  }
  foreach ($commandName in @("python", "python3")) {
    $command = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($command -and $command.Source) { $pythonCandidates += $command.Source }
  }
  if ($env:LOCALAPPDATA) {
    $pythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
  }
  $pythonCandidates += "C:\Program Files\Python312\python.exe"
}

$python = $null
foreach ($candidate in ($pythonCandidates | Select-Object -Unique)) {
  if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
  & $candidate $preflight --quiet 2>$null
  if ($LASTEXITCODE -eq 0) {
    $python = $candidate
    break
  }
}

if (-not $python) {
  if ($env:DATA_AUTOMATION_WORKER_PYTHON -and (Test-Path -LiteralPath $env:DATA_AUTOMATION_WORKER_PYTHON -PathType Leaf)) {
    & $env:DATA_AUTOMATION_WORKER_PYTHON $preflight
  }
  throw "Python 3.12 x64 was not found. Install the python.org Windows installer (64-bit), then run npm run dist:win again. Do not use ARM64 Python for this x64 package."
}

Write-Output "Using build interpreter: $python"
& $python -c "import PyInstaller, openpyxl, playwright"
if ($LASTEXITCODE -ne 0) {
  Write-Output "Installing pinned Worker build dependencies into Python 3.12 x64..."
  & $python -m pip install -r (Join-Path $workerRoot "requirements-build.txt")
  if ($LASTEXITCODE -ne 0) { throw "Unable to install Worker build dependencies into Python 3.12 x64." }
}
$playwrightPackage = (& $python -c "from pathlib import Path; import playwright; print(Path(playwright.__file__).resolve().parent)").Trim()
$playwrightDriver = Join-Path $playwrightPackage "driver"
if (-not (Test-Path -LiteralPath (Join-Path $playwrightDriver "node.exe") -PathType Leaf)) {
  throw "Playwright driver node.exe was not found. Reinstall the pinned Python dependencies."
}

$buildBase = if ($env:DATA_AUTOMATION_WORKER_BUILD_ROOT) {
  [IO.Path]::GetFullPath($env:DATA_AUTOMATION_WORKER_BUILD_ROOT)
} elseif ($env:LOCALAPPDATA) {
  Join-Path $env:LOCALAPPDATA "DataAutomationTool\build"
} else {
  Join-Path ([IO.Path]::GetTempPath()) "DataAutomationTool\build"
}
$stagingRoot = Join-Path $buildBase ("worker-{0}" -f [guid]::NewGuid().ToString("N"))
$pyInstallerDist = Join-Path $stagingRoot "dist"
$pyInstallerWork = Join-Path $stagingRoot "work"
$pyInstallerSpec = Join-Path $stagingRoot "spec"
$dist = if ($env:DATA_AUTOMATION_WORKER_DIST) {
  [IO.Path]::GetFullPath($env:DATA_AUTOMATION_WORKER_DIST)
} else {
  Join-Path $workerRoot "dist"
}
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
Set-Location -LiteralPath $projectRoot

try {
  & $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --noconsole `
    --name="DataAutomationToolWorker" `
    --distpath="$pyInstallerDist" `
    --workpath="$pyInstallerWork" `
    --specpath="$pyInstallerSpec" `
    --paths="$projectRoot" `
    --contents-directory="." `
    --collect-all=playwright `
    --hidden-import=batch_runner `
    --hidden-import=wheat_expansion.exporter `
    --hidden-import=pomelo_keywords_export `
    --hidden-import=pomelo_downloader `
    "web_workbench\worker\run_worker.py"
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller Worker build failed." }

  $stagedDist = Join-Path $stagingRoot "dist\DataAutomationToolWorker"
  if (-not (Test-Path -LiteralPath (Join-Path $stagedDist "DataAutomationToolWorker.exe") -PathType Leaf)) {
    throw "Worker executable was not produced."
  }
  $stagedPlaywright = Join-Path $stagedDist "playwright"
  New-Item -ItemType Directory -Force -Path $stagedPlaywright | Out-Null
  $stagedDriver = Join-Path $stagedPlaywright "driver"
  if (Test-Path -LiteralPath $stagedDriver) { Remove-Item -LiteralPath $stagedDriver -Recurse -Force }
  Copy-Item -LiteralPath $playwrightDriver -Destination $stagedDriver -Recurse -Force
  $driverNodeCopied = Test-Path -LiteralPath (Join-Path $stagedPlaywright "driver\node.exe") -PathType Leaf
  $driverCliCopied = Test-Path -LiteralPath (Join-Path $stagedPlaywright "driver\package\cli.js") -PathType Leaf
  if (-not $driverNodeCopied -or -not $driverCliCopied) {
    throw "Playwright driver was not copied into the standalone Worker."
  }
  if (Test-Path -LiteralPath $dist) { Remove-Item -LiteralPath $dist -Recurse -Force }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dist) | Out-Null
  Move-Item -LiteralPath $stagedDist -Destination $dist
} finally {
  if (Test-Path -LiteralPath $stagingRoot) { Remove-Item -LiteralPath $stagingRoot -Recurse -Force }
}

Write-Output "Worker package: $(Join-Path $dist 'DataAutomationToolWorker.exe')"

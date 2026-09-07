$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath ".."
$env:DATA_AUTOMATION_SESSION_SECRET = if ($env:DATA_AUTOMATION_SESSION_SECRET) { $env:DATA_AUTOMATION_SESSION_SECRET } else { [guid]::NewGuid().ToString("N") }
python -m web_workbench.worker.run_worker

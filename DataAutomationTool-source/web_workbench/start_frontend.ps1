$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "frontend")
npm run dev

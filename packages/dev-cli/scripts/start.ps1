param(
    [string]$FrontendCommand = "<FRONTEND_START_COMMAND>",
    [string]$BackendCommand = "<BACKEND_START_COMMAND>"
)

$ErrorActionPreference = "Stop"

Write-Host "Starting <APP_NAME> local services"
Write-Host "Frontend URL: <FRONTEND_URL>"
Write-Host "Backend URL: <BACKEND_URL>"

if ($FrontendCommand -like "<*>" -or $BackendCommand -like "<*>") {
    Write-Host "Update scripts/start.ps1 with the real project commands before using it."
    exit 1
}

Write-Host "Run frontend command:"
Write-Host $FrontendCommand

Write-Host "Run backend command:"
Write-Host $BackendCommand

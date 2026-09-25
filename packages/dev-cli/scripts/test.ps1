$ErrorActionPreference = "Stop"

$TestCommand = $env:TEST_COMMAND
if ([string]::IsNullOrWhiteSpace($TestCommand)) {
    $TestCommand = "<TEST_COMMAND>"
}

if ($TestCommand -like "<*>") {
    Write-Host "Set TEST_COMMAND or update scripts/test.ps1 with the real validation command."
    exit 1
}

Write-Host "Running validation:"
Write-Host $TestCommand
Invoke-Expression $TestCommand

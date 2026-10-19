# simplicio-tasks installer (thin launcher -> scripts/install_lib.py)
# Usage: pwsh scripts/install.ps1 <runtime> [-Global] [-Target DIR]
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$minimum = [version]"3.11"  # requires-python of pyproject.toml

# A python that really runs: it prints its version, exits 0, and that version is at least $minimum. The Microsoft Store alias
# (...\WindowsApps\python.exe) exits non-zero and prints no version, so it is never used.
function Test-UsablePython([string]$exe) {
  $ErrorActionPreference = "Continue"  # the stderr of a native program must not stop this script
  $text = (& $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null | Out-String).Trim()
  return ($LASTEXITCODE -eq 0) -and ($text -match '^\d+\.\d+$') -and ([version]$text -ge $minimum)
}

# The first usable python among every python3 and python on PATH, in PATH order.
function Find-Python {
  $found = Get-Command python3, python -All -CommandType Application -ErrorAction SilentlyContinue |
    ForEach-Object { $_.Source } | Select-Object -Unique
  foreach ($exe in $found) {
    if (Test-UsablePython $exe) { return $exe }
  }
  return $null
}

$py = Find-Python
if (-not $py -and (Get-Command winget -ErrorAction SilentlyContinue)) {
  Write-Host "No usable Python $minimum or newer was found: installing Python.Python.3.11 with winget."
  & winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) { Write-Warning "winget did not finish (exit $LASTEXITCODE)" }
  # winget changes the registry PATH for new sessions only: add it to this session's PATH so the new Python can be found.
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
  $py = Find-Python
}
if (-not $py -and (Get-Command uv -ErrorAction SilentlyContinue)) {
  & uv python install 3.11
  $found = (& uv python find 3.11 2>$null | Out-String).Trim()
  if ($found -and (Test-UsablePython $found)) { $py = $found }
}
if (-not $py) {
  [Console]::Error.WriteLine("No usable Python $minimum or newer was found. A python command that only opens the Microsoft Store runs nothing. Install Python with: winget install -e --id Python.Python.3.11 (or from https://www.python.org/downloads/), open a new terminal, and run this installer again.")
  exit 1
}
# pass args through; map -Global/-Target to the python flags
$pyArgs = @("$dir/install_lib.py")
foreach ($a in $args) {
  switch ($a) {
    "-Global"         { $pyArgs += "--global" }
    "-Target"         { $pyArgs += "--target" }
    "-SkipOperators"  { $pyArgs += "--skip-operators" }
    default           { $pyArgs += $a }
  }
}
& $py @pyArgs
exit $LASTEXITCODE

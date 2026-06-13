# Local CI simulation for Windows - mirrors ci-local.sh / the GitHub Actions pipeline.
# Usage: .\ci-local.ps1 [-Fix]
#
# Runs the same five gates as ci-local.sh: ruff format, ruff lint, mypy
# (core + providers), pytest, and the desloppify objective-score gate.
# Prefers `uv run --group dev` when uv is available (matching ci-local.sh);
# otherwise falls back to pip-installed pinned tools + the system Python,
# matching what GitHub Actions does.

[CmdletBinding()]
param(
    [switch]$Fix
)

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

$script:Pass = 0
$script:Fail = 0
$script:Results = @()

function Write-Info($msg) { Write-Host "> $msg" -ForegroundColor Yellow }
function Add-Ok($msg) { $script:Pass++; $script:Results += "  [PASS] $msg" }
function Add-Fail($msg, $detail) { $script:Fail++; $script:Results += "  [FAIL] ${msg}: $detail" }
function Add-Warn($msg) { $script:Results += "  [WARN] $msg" }

# Run a Python module (ruff/mypy/pytest) through the active runner. The tool's
# exit code is left in $LASTEXITCODE for the caller to inspect.
function Invoke-Py {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    if ($script:UseUv) { & uv run --group dev python @Args } else { & python @Args }
}

# Run the desloppify CLI through the active runner.
function Invoke-Desloppify {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    if ($script:UseUv) { & uv run --group dev desloppify @Args } else { & desloppify @Args }
}

# True if a Python module is importable/runnable under the active runner.
function Test-PyModule([string[]]$ModuleArgs) {
    Invoke-Py @ModuleArgs *> $null
    return ($LASTEXITCODE -eq 0)
}

# -- Tool bootstrap ----------------------------------------------------------
Write-Info "Checking tools..."

$script:UseUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)

if (-not $script:UseUv) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "FAILED - no 'uv' and no 'python' on PATH" -ForegroundColor Red
        exit 1
    }
    # Ensure pinned tool versions are present (mirrors the GitHub workflow).
    $need = @()
    if (-not (Test-PyModule @("-m", "ruff", "--version"))) { $need += "ruff==0.15.13" }
    if (-not (Test-PyModule @("-m", "mypy", "--version"))) { $need += "mypy==2.1.0" }
    if (-not (Test-PyModule @("-m", "pytest", "--version"))) { $need += "pytest==9.0.3" }
    & desloppify --version *> $null
    if ($LASTEXITCODE -ne 0) { $need += "desloppify==0.9.3" }
    if ($need.Count -gt 0) {
        Write-Host "  Installing missing tools: $($need -join ' ')"
        & python -m pip install --quiet @need
    }
}

# Verify ruff + mypy are reachable (hard requirement, as in ci-local.sh).
if (-not (Test-PyModule @("-m", "ruff", "--version"))) {
    Add-Fail "tool bootstrap" "ruff unavailable"
    Write-Host "FAILED - $($script:Fail) check(s) failed, $($script:Pass) passed" -ForegroundColor Red
    exit 1
}
if (-not (Test-PyModule @("-m", "mypy", "--version"))) {
    Add-Fail "tool bootstrap" "mypy unavailable"
    Write-Host "FAILED - $($script:Fail) check(s) failed, $($script:Pass) passed" -ForegroundColor Red
    exit 1
}

$script:HavePytest = Test-PyModule @("-m", "pytest", "--version")
if (-not $script:HavePytest) { Add-Warn "pytest: unavailable, skipped" }

Invoke-Desloppify --version *> $null
$script:HaveDesloppify = ($LASTEXITCODE -eq 0)
if (-not $script:HaveDesloppify) { Add-Warn "desloppify: unavailable, skipped" }

# -- 1. Ruff format ----------------------------------------------------------
Write-Info "[1/5] Ruff format..."
if ($Fix) {
    Invoke-Py -m ruff format rikugan/
    if ($LASTEXITCODE -eq 0) { Add-Ok "ruff format (auto-fixed)" } else { Add-Fail "ruff format" "failed" }
}
else {
    Invoke-Py -m ruff format --check rikugan/
    if ($LASTEXITCODE -eq 0) { Add-Ok "ruff format" } else { Add-Fail "ruff format" "run with -Fix to auto-fix" }
}

# -- 2. Ruff lint ------------------------------------------------------------
Write-Info "[2/5] Ruff lint..."
if ($Fix) {
    Invoke-Py -m ruff check rikugan/ --fix
    if ($LASTEXITCODE -eq 0) { Add-Ok "ruff lint (auto-fixed)" } else { Add-Fail "ruff lint" "see above" }
}
else {
    Invoke-Py -m ruff check rikugan/
    if ($LASTEXITCODE -eq 0) { Add-Ok "ruff lint" } else { Add-Fail "ruff lint" "see above" }
}

# -- 3. Mypy (core + providers) ----------------------------------------------
Write-Info "[3/5] Mypy (core + providers)..."
$mypyOut = Invoke-Py -m mypy rikugan/core rikugan/providers --pretty 2>&1 | Out-String
if ($LASTEXITCODE -eq 0) {
    Add-Ok "mypy"
}
else {
    # Only count real errors, not informational notes.
    $errorCount = ([regex]::Matches($mypyOut, '(?m): error:')).Count
    if ($errorCount -gt 0) {
        Write-Host $mypyOut
        Add-Fail "mypy" "$errorCount error(s)"
    }
    else {
        Add-Ok "mypy (warnings only)"
    }
}

# -- 4. Pytest ---------------------------------------------------------------
Write-Info "[4/5] Pytest..."
if ($script:HavePytest) {
    Invoke-Py -m pytest tests/ --tb=short -q
    if ($LASTEXITCODE -eq 0) { Add-Ok "pytest" } else { Add-Fail "pytest" "see above" }
}
else {
    Add-Warn "pytest: not installed, skipped"
}

# -- 5. Desloppify objective score gate --------------------------------------
Write-Info "[5/5] Desloppify (objective score)..."
if ($script:HaveDesloppify) {
    Invoke-Desloppify scan --profile objective --no-badge 2>&1 | Select-Object -Last 5

    $baseline = 89.0
    $tolerance = 0.5
    $score = 0.0
    try {
        $data = Get-Content ".desloppify/query.json" -Raw -ErrorAction Stop | ConvertFrom-Json
        $score = [double]$data.objective_score
    }
    catch {
        $score = 0.0
    }

    if ($score -lt ($baseline - $tolerance)) {
        Add-Fail "desloppify" "objective score $score below baseline $baseline (tolerance $tolerance)"
    }
    else {
        Add-Ok "desloppify (objective: $score/100, baseline: $baseline)"
    }
}
else {
    Add-Warn "desloppify: not found, skipped"
}

# -- Summary -----------------------------------------------------------------
Write-Host ""
Write-Host "-- CI Results --------------------------------------------" -ForegroundColor White
foreach ($r in $script:Results) {
    if ($r -like "*[PASS]*") { Write-Host $r -ForegroundColor Green }
    elseif ($r -like "*[FAIL]*") { Write-Host $r -ForegroundColor Red }
    else { Write-Host $r -ForegroundColor Yellow }
}
Write-Host ""

if ($script:Fail -gt 0) {
    Write-Host "FAILED - $($script:Fail) check(s) failed, $($script:Pass) passed" -ForegroundColor Red
    exit 1
}
else {
    Write-Host "ALL PASSED - $($script:Pass) checks" -ForegroundColor Green
    exit 0
}

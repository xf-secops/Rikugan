# ──────────────────────────────────────────────────────────────────────
# Rikugan — universal installer (Windows)
#
#   irm https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.ps1 | iex
#
# Or with arguments:
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.ps1))) -Target ida
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.ps1))) -Target binja
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.ps1))) -Target both
#
# Environment variables:
#   RIKUGAN_DIR     — where to clone the repo   (default: ~\.rikugan)
#   RIKUGAN_BRANCH  — git branch to check out   (default: main)
#   IDADIR          — override IDA install dir  (forwarded to install_ida.bat)
#   IDA_PYTHON      — override Python for IDA    (forwarded to install_ida.bat)
#   BN_PYTHON       — override Python for BN     (forwarded to install_binaryninja.bat)
# ──────────────────────────────────────────────────────────────────────

param(
    [ValidateSet("ida", "binja", "both", "")]
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/buzzer-re/Rikugan.git"
$InstallDir = if ($env:RIKUGAN_DIR) { $env:RIKUGAN_DIR } else { Join-Path $HOME ".rikugan" }
$Branch = if ($env:RIKUGAN_BRANCH) { $env:RIKUGAN_BRANCH } else { "main" }

# ── Helpers ──────────────────────────────────────────────────────────
function Write-Info    { param($Msg) Write-Host "[*] $Msg" -ForegroundColor Cyan }
function Write-Ok      { param($Msg) Write-Host "[+] $Msg" -ForegroundColor Green }
function Write-Warn    { param($Msg) Write-Host "[!] $Msg" -ForegroundColor Yellow }
function Write-Err     { param($Msg) Write-Host "[-] $Msg" -ForegroundColor Red }

function Show-Banner {
    Write-Host ""
    Write-Host "    +==========================================+" -ForegroundColor White
    Write-Host "    |            六眼  Rikugan                 |" -ForegroundColor White
    Write-Host "    |     Reverse Engineering AI Agent         |" -ForegroundColor White
    Write-Host "    |        IDA Pro  .  Binary Ninja          |" -ForegroundColor White
    Write-Host "    +==========================================+" -ForegroundColor White
    Write-Host ""
}

# ── Detection ────────────────────────────────────────────────────────
function Test-IDA {
    # Registry
    $regPaths = @(
        "HKCU:\Software\Hex-Rays\IDA",
        "HKLM:\SOFTWARE\Hex-Rays\IDA"
    )
    foreach ($rp in $regPaths) {
        if (Test-Path $rp) { return $true }
    }
    # AppData user dir
    $idaDir = Join-Path $env:APPDATA "Hex-Rays\IDA Pro"
    if (Test-Path $idaDir) { return $true }
    # USERPROFILE\.idapro
    $idapro = Join-Path $HOME ".idapro"
    if (Test-Path $idapro) { return $true }
    # IDA in PATH
    if (Get-Command "ida64.exe" -ErrorAction SilentlyContinue) { return $true }
    if (Get-Command "idat64.exe" -ErrorAction SilentlyContinue) { return $true }
    return $false
}

function Test-BinaryNinja {
    # AppData user dir
    $bnDir = Join-Path $env:APPDATA "Binary Ninja"
    if (Test-Path $bnDir) { return $true }
    # Common install locations
    $installPaths = @(
        "${env:ProgramFiles}\Vector35\BinaryNinja",
        "${env:ProgramFiles(x86)}\Vector35\BinaryNinja",
        "${env:LOCALAPPDATA}\Vector35\BinaryNinja"
    )
    foreach ($p in $installPaths) {
        if (Test-Path $p) { return $true }
    }
    return $false
}

function Find-ByteSequenceIndex {
    param(
        [byte[]]$Data,
        [byte[]]$Needle
    )

    if (-not $Data -or -not $Needle -or $Needle.Length -eq 0 -or $Needle.Length -gt $Data.Length) {
        return -1
    }

    for ($i = 0; $i -le ($Data.Length - $Needle.Length); $i++) {
        $matched = $true
        for ($j = 0; $j -lt $Needle.Length; $j++) {
            if ($Data[$i + $j] -ne $Needle[$j]) {
                $matched = $false
                break
            }
        }
        if ($matched) {
            return $i
        }
    }

    return -1
}

function Get-IdaUserDir {
    $candidates = @()

    if ($env:APPDATA) {
        $candidates += (Join-Path $env:APPDATA "Hex-Rays\IDA Pro")
    }
    if ($HOME) {
        $candidates += (Join-Path $HOME ".idapro")
    }
    if ($env:IDAUSR) {
        $candidates += $env:IDAUSR
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    if ($env:APPDATA) {
        return (Join-Path $env:APPDATA "Hex-Rays\IDA Pro")
    }

    return $null
}

function Get-IdaInstallDir {
    if ($env:IDADIR -and (Test-Path $env:IDADIR)) {
        return $env:IDADIR
    }

    $regPaths = @(
        "HKCU:\Software\Hex-Rays\IDA",
        "HKLM:\SOFTWARE\Hex-Rays\IDA",
        "HKLM:\SOFTWARE\WOW6432Node\Hex-Rays\IDA"
    )
    foreach ($rp in $regPaths) {
        try {
            $location = (Get-ItemProperty -Path $rp -ErrorAction Stop).Location
            if ($location -and (Test-Path $location)) {
                return $location
            }
        }
        catch {
        }
    }

    foreach ($name in @("ida64.exe", "idat64.exe", "ida.exe", "idat.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            return (Split-Path -Parent $command.Source)
        }
    }

    $installPaths = @(
        "${env:ProgramFiles}\Hex-Rays\IDA Pro",
        "${env:ProgramFiles}\Hex-Rays\IDA Professional",
        "${env:ProgramFiles}\IDA Pro",
        "${env:ProgramFiles(x86)}\Hex-Rays\IDA Pro",
        "${env:ProgramFiles(x86)}\Hex-Rays\IDA Professional",
        "${env:ProgramFiles(x86)}\IDA Pro"
    )
    foreach ($path in $installPaths) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }

    return $null
}

function Get-IdaRegPythonTarget {
    param([string]$UserDir)

    if (-not $UserDir) {
        return $null
    }

    $regFile = Join-Path $UserDir "ida.reg"
    if (-not (Test-Path $regFile -PathType Leaf)) {
        return $null
    }

    try {
        $data = [System.IO.File]::ReadAllBytes($regFile)
    }
    catch {
        return $null
    }

    $needle = [System.Text.Encoding]::ASCII.GetBytes("Python3TargetDLL")
    $idx = Find-ByteSequenceIndex -Data $data -Needle $needle
    if ($idx -lt 0) {
        return $null
    }

    $keyEnd = $idx
    while ($keyEnd -lt $data.Length -and $data[$keyEnd] -ne 0) {
        $keyEnd++
    }

    if (($keyEnd + 6) -gt $data.Length) {
        return $null
    }

    $length = [System.BitConverter]::ToInt32($data, $keyEnd + 1)
    if ($length -le 0 -or $length -gt 4096) {
        return $null
    }

    $valueStart = $keyEnd + 6
    if (($valueStart + $length) -gt $data.Length) {
        return $null
    }

    [byte[]]$valueBytes = $data[$valueStart..($valueStart + $length - 1)]
    $path = [System.Text.Encoding]::UTF8.GetString($valueBytes).Trim([char]0, ' ')
    if ($path -match '^(?:[A-Za-z]:\\|\\\\)') {
        return $path
    }

    return $null
}

function Resolve-IdaPythonExecutable {
    param([string]$TargetPath)

    if (-not $TargetPath) {
        return $null
    }

    $target = $TargetPath.Trim().Trim('"').Trim("'")
    if (-not $target) {
        return $null
    }

    if (Test-Path $target -PathType Leaf) {
        $leaf = [System.IO.Path]::GetFileName($target)
        if ($leaf -match '^python(?:3|[0-9]+)?\.exe$') {
            return $target
        }
    }

    $candidates = [System.Collections.Generic.List[string]]::new()

    if (Test-Path $target -PathType Container) {
        $candidates.Add((Join-Path $target "python.exe"))
        $candidates.Add((Join-Path $target "python3.exe"))
    }
    else {
        $parent = Split-Path -Parent $target
        $leaf = [System.IO.Path]::GetFileName($target)

        if ($leaf -match '^python([0-9]+)?\.dll$') {
            $digits = $Matches[1]
            if ($digits) {
                $candidates.Add((Join-Path $parent "python$digits.exe"))
            }
            $candidates.Add((Join-Path $parent "python.exe"))
            $candidates.Add((Join-Path $parent "python3.exe"))
        }
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate -PathType Leaf)) {
            return $candidate
        }
    }

    if ($leaf -match '^python([0-9]+)\.dll$') {
        $digits = $Matches[1]
        if ($digits.Length -ge 2) {
            $versionName = "python$($digits.Substring(0, 1)).$($digits.Substring(1))"
            $command = Get-Command $versionName -ErrorAction SilentlyContinue
            if ($command -and $command.Source) {
                return $command.Source
            }
        }
    }

    return $null
}

function Get-IdaPython {
    $userDir = Get-IdaUserDir
    $pythonTarget = Get-IdaRegPythonTarget -UserDir $userDir
    $resolved = Resolve-IdaPythonExecutable -TargetPath $pythonTarget
    if ($resolved) {
        return $resolved
    }

    $installDir = Get-IdaInstallDir
    if (-not $installDir) {
        return $null
    }

    $bundledDirs = Get-ChildItem -Path (Join-Path $installDir "python3*") -Directory -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    foreach ($dir in $bundledDirs) {
        foreach ($name in @("python.exe", "python3.exe")) {
            $candidate = Join-Path $dir.FullName $name
            if (Test-Path $candidate -PathType Leaf) {
                return $candidate
            }
        }
    }

    foreach ($candidate in @(
        (Join-Path $installDir "python\python.exe"),
        (Join-Path $installDir "python\python3.exe")
    )) {
        if (Test-Path $candidate -PathType Leaf) {
            return $candidate
        }
    }

    $idapyswitch = Join-Path $installDir "idapyswitch.exe"
    if (Test-Path $idapyswitch -PathType Leaf) {
        $lines = & $idapyswitch --show-current 2>$null
        foreach ($line in $lines) {
            $target = $line.Trim().Trim("'")
            if ($target -like "Path:*") {
                $target = $target.Substring(5).Trim()
            }
            $resolved = Resolve-IdaPythonExecutable -TargetPath $target
            if ($resolved) {
                return $resolved
            }
        }
    }

    return $null
}

# ── Prerequisites ────────────────────────────────────────────────────
function Test-Prerequisites {
    if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) {
        Write-Err "git is required but not installed."
        Write-Err "Install from: https://git-scm.com/download/win"
        Write-Err "Or: winget install Git.Git"
        exit 1
    }
}

# ── Clone or update ──────────────────────────────────────────────────
function Install-Repository {
    $gitDir = Join-Path $InstallDir ".git"
    if (Test-Path $gitDir) {
        Write-Info "Updating existing installation at $InstallDir..."
        git -C $InstallDir fetch origin $Branch --quiet 2>$null
        git -C $InstallDir checkout $Branch --quiet 2>$null
        git -C $InstallDir reset --hard "origin/$Branch" --quiet 2>$null
        Write-Ok "Updated to latest $Branch"
    }
    else {
        if (Test-Path $InstallDir) {
            $backup = "${InstallDir}.bak.$(Get-Date -Format 'yyyyMMddHHmmss')"
            Write-Warn "$InstallDir exists but is not a git repo -- backing up to $backup"
            Rename-Item $InstallDir $backup
        }
        Write-Info "Cloning Rikugan into $InstallDir..."
        git clone --branch $Branch --depth 1 $RepoUrl $InstallDir --quiet 2>$null
        Write-Ok "Cloned successfully"
    }
}

# ── Run installers ───────────────────────────────────────────────────
function Install-IDA {
    $script = Join-Path $InstallDir "install_ida.bat"
    if (-not (Test-Path $script)) {
        Write-Err "install_ida.bat not found in $InstallDir"
        return $false
    }
    Write-Info "Running IDA Pro installer..."
    Write-Host ""
    $setIdaPython = $false
    if (-not $env:IDA_PYTHON) {
        $resolvedIdaPython = Get-IdaPython
        if ($resolvedIdaPython) {
            Write-Info "Resolved IDA Python: $resolvedIdaPython"
            $env:IDA_PYTHON = $resolvedIdaPython
            $setIdaPython = $true
        }
        else {
            Write-Warn "Could not resolve IDA's configured Python, falling back to installer-side detection."
        }
    }
    Push-Location $InstallDir
    try {
        & cmd.exe /c $script
        $success = $LASTEXITCODE -eq 0
    }
    finally {
        Pop-Location
        if ($setIdaPython) {
            Remove-Item Env:IDA_PYTHON -ErrorAction SilentlyContinue
        }
    }
    return $success
}

function Install-BinaryNinja {
    $script = Join-Path $InstallDir "install_binaryninja.bat"
    if (-not (Test-Path $script)) {
        Write-Err "install_binaryninja.bat not found in $InstallDir"
        return $false
    }
    Write-Info "Running Binary Ninja installer..."
    Write-Host ""
    Push-Location $InstallDir
    try {
        & cmd.exe /c $script
        $success = $LASTEXITCODE -eq 0
    }
    finally { Pop-Location }
    return $success
}

# ── Main ─────────────────────────────────────────────────────────────
Show-Banner
Test-Prerequisites

# Auto-detect if no target specified
if (-not $Target) {
    $hasIda = Test-IDA
    $hasBinja = Test-BinaryNinja

    if ($hasIda -and $hasBinja) {
        $Target = "both"
        Write-Ok "Detected both IDA Pro and Binary Ninja"
    }
    elseif ($hasIda) {
        $Target = "ida"
        Write-Ok "Detected IDA Pro"
    }
    elseif ($hasBinja) {
        $Target = "binja"
        Write-Ok "Detected Binary Ninja"
    }
    else {
        Write-Warn "No IDA Pro or Binary Ninja installation detected."
        Write-Warn "Installing anyway -- defaulting to both."
        $Target = "both"
    }
}

Write-Info "Target: $Target"
Write-Info "Install directory: $InstallDir"
Write-Host ""

Install-Repository
Write-Host ""

$failed = $false

switch ($Target) {
    "ida" {
        if (-not (Install-IDA)) { $failed = $true }
    }
    "binja" {
        if (-not (Install-BinaryNinja)) { $failed = $true }
    }
    "both" {
        if (-not (Install-IDA))   { Write-Warn "IDA installation failed"; $failed = $true }
        Write-Host ""
        if (-not (Install-BinaryNinja)) { Write-Warn "Binary Ninja installation failed"; $failed = $true }
    }
}

Write-Host ""
if ($failed) {
    Write-Warn "Installation completed with errors. Check the output above."
}
else {
    Write-Ok "Rikugan installation complete!"
}
Write-Host "  Install location: $InstallDir" -ForegroundColor DarkGray
Write-Host "  To update later:  cd $InstallDir; git pull" -ForegroundColor DarkGray
Write-Host ""

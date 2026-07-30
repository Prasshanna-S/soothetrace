[CmdletBinding()]
param(
    [switch]$InstallTools,
    [switch]$InstallPlaywright
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPath = Join-Path $RepoRoot ".venv"
$PythonPath = Join-Path $VenvPath "Scripts\python.exe"
$RequirementsPath = Join-Path $RepoRoot "requirements.txt"
$CorpusRoot = Join-Path $RepoRoot "experiments\donateacry-corpus"
$CorpusAudioRoot = Join-Path $CorpusRoot "donateacry_corpus_cleaned_and_updated_data"
$BaselineScript = Join-Path $RepoRoot "tools\build_baseline.py"

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Install-WinGetPackage {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Command "winget")) {
        throw "WinGet is required to install $Label. Install or update App Installer, reopen PowerShell, and retry."
    }
    Write-Host "Installing $Label with WinGet..."
    & winget install --id $Id --exact --source winget `
        --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "WinGet could not install $Label ($Id)."
    }
}

$RequiredTools = @(
    @{ Command = "git"; Id = "Git.Git"; Label = "Git for Windows" },
    @{ Command = "uv"; Id = "astral-sh.uv"; Label = "uv" },
    @{ Command = "ffmpeg"; Id = "Gyan.FFmpeg"; Label = "FFmpeg" }
)

foreach ($Tool in $RequiredTools) {
    if (-not (Test-Command $Tool.Command)) {
        if (-not $InstallTools) {
            throw "$($Tool.Label) is missing. Rerun with -InstallTools, then reopen PowerShell if PATH changed."
        }
        Install-WinGetPackage -Id $Tool.Id -Label $Tool.Label
    }
}

if ($InstallTools -and -not (Test-Command "ffprobe")) {
    throw "Tool installation changed PATH. Reopen PowerShell, return to the repository, and rerun this script."
}

foreach ($Command in @("git", "uv", "ffmpeg", "ffprobe")) {
    if (-not (Test-Command $Command)) {
        throw "$Command is not on PATH. Reopen PowerShell after installation and retry."
    }
}

if ($InstallPlaywright -and -not (Test-Command "node")) {
    if (-not $InstallTools) {
        throw "Node.js LTS is missing. Rerun with -InstallTools -InstallPlaywright."
    }
    Install-WinGetPackage -Id "OpenJS.NodeJS.LTS" -Label "Node.js LTS"
}

if ($InstallPlaywright) {
    foreach ($Command in @("node", "npm", "npx")) {
        if (-not (Test-Command $Command)) {
            throw "$Command is required for the optional browser interaction check. Reopen PowerShell if Node.js was just installed."
        }
    }
}

Push-Location $RepoRoot
try {
    Write-Host "Installing managed Python 3.12..."
    & uv python install 3.12
    if ($LASTEXITCODE -ne 0) {
        throw "uv could not install Python 3.12."
    }

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        Write-Host "Creating virtual environment at $VenvPath..."
        & uv venv $VenvPath --python 3.12
        if ($LASTEXITCODE -ne 0) {
            throw "uv could not create the Python 3.12 virtual environment."
        }
    }

    $PythonVersion = (& $PythonPath -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    if ($LASTEXITCODE -ne 0 -or $PythonVersion -notmatch "^3\.12\.") {
        throw "Expected Python 3.12 at $PythonPath, found '$PythonVersion'. Remove .venv and rerun setup."
    }

    Write-Host "Installing Python dependencies into $PythonPath..."
    & uv pip install --python $PythonPath -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed."
    }

    & $PythonPath -c "import cryptography, numpy, scipy, soundfile, torch, torchaudio, speechbrain; assert torch.__version__ == torchaudio.__version__, ('Torch and TorchAudio builds differ', torch.__version__, torchaudio.__version__); print('Dependencies ready:', torch.__version__, torchaudio.__version__, speechbrain.__version__)"
    if ($LASTEXITCODE -ne 0) {
        throw "A required Python acoustic dependency could not be imported."
    }

    if (-not (Test-Path -LiteralPath $CorpusAudioRoot -PathType Container)) {
        if (Test-Path -LiteralPath $CorpusRoot) {
            throw "The corpus directory exists but its expected audio directory is missing: $CorpusAudioRoot"
        }
        Write-Host "Cloning the public baseline corpus..."
        & git clone --depth 1 `
            "https://github.com/gveres/donateacry-corpus.git" `
            $CorpusRoot
        if ($LASTEXITCODE -ne 0) {
            throw "The public baseline corpus clone failed."
        }
    } else {
        Write-Host "Public baseline corpus already present."
    }

    Write-Host "Building the population normalization baseline..."
    & $PythonPath $BaselineScript
    if ($LASTEXITCODE -ne 0) {
        throw "Population baseline generation failed."
    }

    Write-Host "Downloading and warming the required identity models..."
    & $PythonPath -c "from src import encoders, identity; required = sorted(set(identity.ENCODER_FOR_KIND.values())); status = encoders.warm(required); print(status); assert all(status.values()), status"
    if ($LASTEXITCODE -ne 0) {
        throw "One or more identity models failed to load. Keep internet access available and rerun setup."
    }

    if ($InstallPlaywright) {
        Write-Host "Installing the optional local Playwright package and Chromium..."
        & npm install --no-save --package-lock=false playwright
        if ($LASTEXITCODE -ne 0) {
            throw "Playwright package installation failed."
        }
        & npx playwright install chromium
        if ($LASTEXITCODE -ne 0) {
            throw "Playwright Chromium installation failed."
        }
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Windows setup complete."
Write-Host "Python: $PythonPath"
Write-Host "Start the desktop demo with:"
Write-Host "  .\scripts\run_windows.ps1 -Mode Desktop"

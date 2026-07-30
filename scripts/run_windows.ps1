[CmdletBinding()]
param(
    [ValidateSet("Desktop", "Bootstrap", "Phone", "Health")]
    [string]$Mode = "Desktop",

    [string]$LanIp,

    [ValidateRange(0, 65535)]
    [int]$Port = 0,

    [uri]$HealthUri = "http://127.0.0.1:8000/api/health"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$DataRoot = Join-Path $RepoRoot "data\audio"
$StaticRoot = Join-Path $RepoRoot "web"
$DatabasePath = Join-Path $RepoRoot "data\episodes.db"
$CertRoot = Join-Path $RepoRoot "data\audio\mobile-capture-spike\certs"
$RootCertificate = Join-Path $CertRoot "rootCA.pem"
$ServerCertificate = Join-Path $CertRoot "server.pem"
$ServerKey = Join-Path $CertRoot "server.key"
$CertificateScript = Join-Path $RepoRoot "spikes\mobile_capture\make_cert.py"
$BootstrapScript = Join-Path $RepoRoot "spikes\mobile_capture\bootstrap.py"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python environment not found at '$PythonPath'. Run .\scripts\setup_windows.ps1 first."
}

function Assert-LanIp {
    if ([string]::IsNullOrWhiteSpace($LanIp)) {
        throw "-LanIp is required for $Mode mode. Use ipconfig or Get-NetIPConfiguration to find the current IPv4 LAN address."
    }
    $ParsedIp = $null
    if (-not [System.Net.IPAddress]::TryParse($LanIp, [ref]$ParsedIp) -or
        $ParsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw "'$LanIp' is not a valid IPv4 address."
    }
    if ($ParsedIp.Equals([System.Net.IPAddress]::Loopback)) {
        throw "Use the Windows computer's LAN address, not 127.0.0.1."
    }
}

Push-Location $RepoRoot
try {
    switch ($Mode) {
        "Desktop" {
            $ListenPort = if ($Port -eq 0) { 8000 } else { $Port }
            Write-Host "Starting desktop HTTP at http://127.0.0.1:$ListenPort"
            Write-Host "Wait for both encoder values to be True before opening the page."
            & $PythonPath -m src.http_api `
                --http `
                --host 127.0.0.1 `
                --port $ListenPort `
                --data-root $DataRoot `
                --static-root $StaticRoot `
                --db $DatabasePath
            if ($LASTEXITCODE -ne 0) {
                throw "Desktop server exited with code $LASTEXITCODE."
            }
        }
        "Bootstrap" {
            Assert-LanIp
            $ListenPort = if ($Port -eq 0) { 8080 } else { $Port }
            if (-not (Test-Path -LiteralPath $CertificateScript -PathType Leaf)) {
                throw "Portable certificate generator not found at '$CertificateScript'. Update the checkout before using phone HTTPS."
            }
            Write-Host "Generating a temporary certificate for $LanIp..."
            & $PythonPath $CertificateScript $LanIp
            if ($LASTEXITCODE -ne 0) {
                throw "Certificate generation failed."
            }
            if (-not (Test-Path -LiteralPath $RootCertificate -PathType Leaf)) {
                throw "Certificate generation did not create '$RootCertificate'."
            }
            Write-Host "Certificate profile URL:"
            Write-Host "  http://${LanIp}:$ListenPort/Interaction-Memory-Spike-CA-corrected.mobileconfig"
            & $PythonPath $BootstrapScript `
                --host 0.0.0.0 `
                --port $ListenPort `
                --cert $RootCertificate
            if ($LASTEXITCODE -ne 0) {
                throw "Certificate bootstrap server exited with code $LASTEXITCODE."
            }
        }
        "Phone" {
            Assert-LanIp
            $ListenPort = if ($Port -eq 0) { 8443 } else { $Port }
            foreach ($Path in @($ServerCertificate, $ServerKey, $RootCertificate)) {
                if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
                    throw "Certificate file missing at '$Path'. Run .\scripts\run_windows.ps1 -Mode Bootstrap -LanIp $LanIp first."
                }
            }
            & $PythonPath $CertificateScript $LanIp --check-existing
            if ($LASTEXITCODE -ne 0) {
                throw "The server certificate is expired or does not contain the current LAN IP. Run .\scripts\run_windows.ps1 -Mode Bootstrap -LanIp $LanIp and reinstall the profile."
            }
            Write-Host "Starting phone HTTPS at https://${LanIp}:$ListenPort"
            Write-Host "Wait for both encoder values to be True before opening the page."
            & $PythonPath -m src.http_api `
                --host 0.0.0.0 `
                --port $ListenPort `
                --data-root $DataRoot `
                --static-root $StaticRoot `
                --db $DatabasePath `
                --cert $ServerCertificate `
                --key $ServerKey
            if ($LASTEXITCODE -ne 0) {
                throw "Phone HTTPS server exited with code $LASTEXITCODE."
            }
        }
        "Health" {
            Write-Host "Checking $HealthUri"
            $Response = Invoke-RestMethod -Method Get -Uri $HealthUri
            $Response | ConvertTo-Json -Depth 6
            if ($Response.status -ne "ready") {
                throw "Cry Memory health status is '$($Response.status)', not 'ready'."
            }
        }
    }
} finally {
    Pop-Location
}

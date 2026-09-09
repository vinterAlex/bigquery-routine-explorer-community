# Setup script for BigQuery Routine Explorer (Community Edition) secrets.
#
# Usage:
#   .\setup_secrets.ps1                              # create secrets\ folder only
#   .\setup_secrets.ps1 -KeyPath "C:\path\key.json"  # copy + validate a service-account key
#
# This creates the `secrets` folder (mounted read-only into the Docker container
# at /secrets) and, if given a key, installs it as secrets\key.json, which is the
# default path the app reads (override with SA_KEY_PATH).

param(
    [string]$KeyPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretsDir = Join-Path $root "secrets"
$keyTarget = Join-Path $secretsDir "key.json"

Write-Host ""
Write-Host "BigQuery Routine Explorer - COMMUNITY EDITION"
Write-Host "----------------------------------------------"
Write-Host ""

if (-not (Test-Path -LiteralPath $secretsDir)) {
    New-Item -ItemType Directory -Path $secretsDir | Out-Null
    Write-Host "Created $secretsDir"
} else {
    Write-Host "$secretsDir already exists"
}

if ($KeyPath -and (Test-Path -LiteralPath $KeyPath)) {
    Copy-Item -LiteralPath $KeyPath -Destination $keyTarget -Force
    Write-Host "Copied key to $keyTarget"
} elseif ($KeyPath) {
    Write-Host "ERROR: key not found at '$KeyPath'" -ForegroundColor Red
    exit 1
}

# Validate key if present
if (Test-Path -LiteralPath $keyTarget) {
    try {
        $key = Get-Content -LiteralPath $keyTarget -Raw | ConvertFrom-Json
        $ok = $key.type -eq "service_account" -and $key.client_email -and $key.private_key
        if ($ok) {
            Write-Host "OK: valid service-account key ($($key.client_email))" -ForegroundColor Green
        } else {
            Write-Host "WARNING: $keyTarget does not look like a GCP service-account key JSON." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARNING: $keyTarget is not valid JSON." -ForegroundColor Yellow
    }
} else {
    Write-Host "No service-account key found yet."
    Write-Host "Put your read-only BigQuery service-account JSON as secrets\key.json"
    Write-Host "  (or run: .\setup_secrets.ps1 -KeyPath C:\path\to\key.json)"
    Write-Host "Required IAM roles on each project: roles/bigquery.metadataViewer and roles/bigquery.jobUser"
}
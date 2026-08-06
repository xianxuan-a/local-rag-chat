param(
    [switch]$NoBrowser,
    [switch]$AutoUpgrade,
    [string]$RuntimeRoot = $env:LOCAL_RAG_RUNTIME_ROOT,
    [string]$DatabasePath = $env:LOCAL_RAG_DATABASE
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot "frontend"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$launcherConfigPath = Join-Path $projectRoot ".local-rag-chat.json"
$expectedRuntimeId = $null

function Resolve-ProjectPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Path))
}

if (
    [string]::IsNullOrWhiteSpace($RuntimeRoot) -and
    [string]::IsNullOrWhiteSpace($DatabasePath)
) {
    if (-not (Test-Path -LiteralPath $launcherConfigPath)) {
        throw (
            "Fixed local data configuration is missing: $launcherConfigPath. " +
            "Refusing to guess or switch data directories."
        )
    }
    $launcherConfig = Get-Content -LiteralPath $launcherConfigPath -Raw |
        ConvertFrom-Json
    $RuntimeRoot = [string]$launcherConfig.runtime_root
    $DatabasePath = [string]$launcherConfig.database_path
    $expectedRuntimeId = [string]$launcherConfig.runtime_id
}
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    throw "RuntimeRoot is required when DatabasePath is specified explicitly."
}
$runtimeRoot = Resolve-ProjectPath $RuntimeRoot
if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
    $DatabasePath = Join-Path $runtimeRoot "metadata\local_rag_chat.db"
}
$databasePath = Resolve-ProjectPath $DatabasePath
$logRoot = Join-Path $runtimeRoot "logs"
$backupRoot = Join-Path $runtimeRoot "backups\startup-migrations"
$runtimeMarkerPath = Join-Path $runtimeRoot ".local-rag-runtime.json"
$launchStatePath = Join-Path $runtimeRoot ".local-rag-launch-state.json"
$activeRuntimeId = ""

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python virtual environment is missing: $pythonPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules"))) {
    throw "Frontend dependencies are missing. Run npm install in frontend first."
}
if (-not (Test-Path -LiteralPath $databasePath)) {
    throw "The local database is missing: $databasePath"
}
if (Test-Path -LiteralPath $runtimeMarkerPath) {
    $runtimeMarker = Get-Content -LiteralPath $runtimeMarkerPath -Raw |
        ConvertFrom-Json
    $activeRuntimeId = [string]$runtimeMarker.runtime_id
}
if (-not [string]::IsNullOrWhiteSpace($expectedRuntimeId)) {
    if ([string]::IsNullOrWhiteSpace($activeRuntimeId)) {
        throw "Fixed runtime identity file is missing: $runtimeMarkerPath"
    }
    if ($activeRuntimeId -ne $expectedRuntimeId) {
        throw (
            "Fixed runtime identity mismatch. Expected $expectedRuntimeId, " +
            "found $activeRuntimeId. Refusing to start."
        )
    }
}

New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
Write-Host "Fixed data directory: $runtimeRoot"
Write-Host "Database: $databasePath"
if (-not [string]::IsNullOrWhiteSpace($expectedRuntimeId)) {
    Write-Host "Runtime ID: $expectedRuntimeId"
}

function Test-ListeningPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    return $null -ne (
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -First 1
    )
}

function Get-ListeningProcessId {
    param([Parameter(Mandatory = $true)][int]$Port)

    return (
        Get-NetTCPConnection `
            -State Listen `
            -LocalPort $Port `
            -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess
    )
}

function Wait-ListeningPort {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ServiceName
    )

    for ($attempt = 0; $attempt -lt 40; $attempt += 1) {
        if (Test-ListeningPort -Port $Port) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$ServiceName startup timed out. Check logs in $logRoot."
}

$backendListening = Test-ListeningPort -Port 8000
$frontendListening = Test-ListeningPort -Port 5173
if ($backendListening -or $frontendListening) {
    $managedRuntimeRunning = $false
    if (
        $backendListening -and
        $frontendListening -and
        (Test-Path -LiteralPath $launchStatePath)
    ) {
        $launchState = Get-Content -LiteralPath $launchStatePath -Raw |
            ConvertFrom-Json
        $managedRuntimeRunning = (
            [string]$launchState.runtime_id -eq $activeRuntimeId -and
            [int]$launchState.backend_pid -eq
                (Get-ListeningProcessId -Port 8000) -and
            [int]$launchState.frontend_pid -eq
                (Get-ListeningProcessId -Port 5173)
        )
    }
    if ($managedRuntimeRunning) {
        $ready = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/health/ready" `
            -TimeoutSec 10
        if ($ready.data.status -ne "ready") {
            throw "The managed fixed-data backend is running but not ready."
        }
        Write-Host "The fixed-data project is already running."
        if (-not $NoBrowser) {
            Start-Process "http://127.0.0.1:5173/"
        }
        return
    }
    throw (
        "Port 8000 or 5173 belongs to an unknown runtime. Stop the existing " +
        "processes first; refusing to reuse a different database."
    )
}

function Get-DatabaseStatus {
    $statusJson = & $pythonPath `
        (Join-Path $projectRoot "scripts\prepare_local_database.py") `
        status `
        --database $databasePath
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect database schema: $databasePath"
    }
    return $statusJson | ConvertFrom-Json
}

$databaseStatus = Get-DatabaseStatus
if ($databaseStatus.upgrade_required) {
    Write-Host ""
    Write-Host "Database update required: $($databaseStatus.current) -> $($databaseStatus.head)"
    Write-Host "Database: $databasePath"
    Write-Host "A backup will be kept in: $backupRoot"
    Write-Host ""

    $shouldUpgrade = $AutoUpgrade
    if (-not $shouldUpgrade) {
        $confirmation = Read-Host "Update the database and continue? [y/N]"
        $shouldUpgrade = $confirmation -match "^(?i:y|yes)$"
    }
    if (-not $shouldUpgrade) {
        throw "Database update was cancelled. No data was changed."
    }

    $upgradeJson = & $pythonPath `
        (Join-Path $projectRoot "scripts\prepare_local_database.py") `
        upgrade `
        --database $databasePath `
        --backup-dir $backupRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Database update failed. The original database was not replaced."
    }
    $upgradeResult = $upgradeJson | ConvertFrom-Json
    Write-Host "Database updated successfully."
    Write-Host "Backup: $($upgradeResult.backup)"
}

$databaseUrlPath = $databasePath.Replace("\", "/")
$env:DATABASE_URL = "sqlite:///$databaseUrlPath"
$env:DATA_DIR = $runtimeRoot
$env:METADATA_DIR = Join-Path $runtimeRoot "metadata"
$env:UPLOAD_DIR = Join-Path $runtimeRoot "uploads"
$env:CHROMA_DIR = Join-Path $runtimeRoot "chroma"
$env:CHAT_HISTORY_DIR = Join-Path $runtimeRoot "chat_history"
$env:BACKUP_DIR = Join-Path $runtimeRoot "backups"
$env:EVALUATION_DIR = Join-Path $runtimeRoot "evaluations"
$env:LOG_DIR = $logRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Start-Process `
    -FilePath $pythonPath `
    -ArgumentList @("run.py") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logRoot "backend-$stamp.out.log") `
    -RedirectStandardError (Join-Path $logRoot "backend-$stamp.err.log")

Wait-ListeningPort -Port 8000 -ServiceName "Backend"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Start-Process `
    -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev:real", "--", "--host", "127.0.0.1") `
    -WorkingDirectory $frontendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logRoot "frontend-$stamp.out.log") `
    -RedirectStandardError (Join-Path $logRoot "frontend-$stamp.err.log")

Wait-ListeningPort -Port 5173 -ServiceName "Frontend"

$launchState = [ordered]@{
    runtime_id = $activeRuntimeId
    backend_pid = Get-ListeningProcessId -Port 8000
    frontend_pid = Get-ListeningProcessId -Port 5173
    started_at = (Get-Date).ToString("o")
}
$launchState |
    ConvertTo-Json |
    Set-Content -LiteralPath $launchStatePath -Encoding utf8

$ready = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 10
if ($ready.data.status -ne "ready") {
    throw "Backend health check is not ready."
}

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:5173/"
}

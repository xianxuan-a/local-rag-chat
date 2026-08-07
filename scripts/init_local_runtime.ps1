param(
    [string]$RuntimeRoot = $env:LOCAL_RAG_RUNTIME_ROOT,
    [string]$DatabasePath = $env:LOCAL_RAG_DATABASE
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "local_runtime.ps1")

$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$configPath = Join-Path $projectRoot ".local-rag-chat.json"

try {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".env") -PathType Leaf)) {
        throw "缺少 .env。请先执行 Copy-Item .env.example .env 并完成配置。"
    }
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "缺少 Python 虚拟环境：$pythonPath"
    }

    $existingConfig = $null
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        $existingConfig = Read-LocalJsonFile -Path $configPath
        if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
            $RuntimeRoot = [string]$existingConfig.runtime_root
        }
        if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
            $DatabasePath = [string]$existingConfig.database_path
        }
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        throw "必须通过 -RuntimeRoot 或 LOCAL_RAG_RUNTIME_ROOT 指定固定数据目录。"
    }

    $resolvedRuntimeRoot = Resolve-LocalFullPath -Path $RuntimeRoot -BasePath $projectRoot
    if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
        $DatabasePath = Join-Path $resolvedRuntimeRoot "metadata\local_rag_chat.db"
    }
    $resolvedDatabasePath = Resolve-LocalFullPath -Path $DatabasePath -BasePath $projectRoot

    if ($null -ne $existingConfig) {
        if (-not (Test-LocalSamePath -Left ([string]$existingConfig.runtime_root) -Right $resolvedRuntimeRoot)) {
            throw "现有 .local-rag-chat.json 指向其他运行时；已拒绝覆盖。"
        }
        if (-not (Test-LocalSamePath -Left ([string]$existingConfig.database_path) -Right $resolvedDatabasePath)) {
            throw "现有 .local-rag-chat.json 指向其他数据库；已拒绝覆盖。"
        }
    }

    $runtimeId = if (
        $null -ne $existingConfig -and
        -not [string]::IsNullOrWhiteSpace([string]$existingConfig.runtime_id)
    ) {
        [string]$existingConfig.runtime_id
    }
    else {
        [guid]::NewGuid().ToString()
    }
    $markerPath = Join-Path $resolvedRuntimeRoot ".local-rag-runtime.json"
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        $marker = Read-LocalJsonFile -Path $markerPath
        if ([string]$marker.runtime_id -ne $runtimeId) {
            throw "目标目录已有不同的运行时身份，已拒绝接管：$markerPath"
        }
    }

    foreach ($directory in @(
        $resolvedRuntimeRoot,
        (Split-Path -Parent $resolvedDatabasePath),
        (Join-Path $resolvedRuntimeRoot "uploads"),
        (Join-Path $resolvedRuntimeRoot "chroma"),
        (Join-Path $resolvedRuntimeRoot "chat_history"),
        (Join-Path $resolvedRuntimeRoot "backups"),
        (Join-Path $resolvedRuntimeRoot "evaluations"),
        (Join-Path $resolvedRuntimeRoot "logs")
    )) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $databaseUrlPath = $resolvedDatabasePath.Replace("\", "/")
    $env:DATABASE_URL = "sqlite:///$databaseUrlPath"
    $env:DATA_DIR = $resolvedRuntimeRoot
    $env:METADATA_DIR = Split-Path -Parent $resolvedDatabasePath
    $env:UPLOAD_DIR = Join-Path $resolvedRuntimeRoot "uploads"
    $env:CHROMA_DIR = Join-Path $resolvedRuntimeRoot "chroma"
    $env:CHAT_HISTORY_DIR = Join-Path $resolvedRuntimeRoot "chat_history"
    $env:BACKUP_DIR = Join-Path $resolvedRuntimeRoot "backups"
    $env:EVALUATION_DIR = Join-Path $resolvedRuntimeRoot "evaluations"
    $env:LOG_DIR = Join-Path $resolvedRuntimeRoot "logs"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    if (-not (Test-Path -LiteralPath $resolvedDatabasePath -PathType Leaf)) {
        Push-Location $projectRoot
        try {
            & $pythonPath -m alembic upgrade head
            if ($LASTEXITCODE -ne 0) {
                throw "数据库初始化失败；请检查上方 Alembic 输出。"
            }
        }
        finally {
            Pop-Location
        }
    }

    $statusJson = & $pythonPath (Join-Path $projectRoot "scripts\prepare_local_database.py") status --database $resolvedDatabasePath
    if ($LASTEXITCODE -ne 0) {
        throw "数据库结构检查失败：$resolvedDatabasePath"
    }
    $status = $statusJson | ConvertFrom-Json
    if ($status.upgrade_required) {
        throw "数据库不是最新版本；请执行启动命令并选择备份升级。"
    }

    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        Write-LocalJsonAtomic -Path $markerPath -Value ([ordered]@{
            schema_version = 1
            runtime_id = $runtimeId
            project_root = $projectRoot
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        })
    }
    Write-LocalJsonAtomic -Path $configPath -Value ([ordered]@{
        runtime_id = $runtimeId
        runtime_root = $resolvedRuntimeRoot
        database_path = $resolvedDatabasePath
    })

    Write-Host "本地运行时初始化完成。"
    Write-Host "固定数据目录：$resolvedRuntimeRoot"
    Write-Host "数据库：$resolvedDatabasePath"
    Write-Host "下一步：.\启动项目.cmd"
    exit 0
}
catch {
    [Console]::Error.WriteLine("初始化失败：$($_.Exception.Message)")
    [Console]::Error.WriteLine("不会自动删除已有文件；请核对提示后重试。")
    exit 1
}

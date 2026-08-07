param(
    [switch]$NoBrowser,
    [switch]$AutoUpgrade,
    [string]$RuntimeRoot = $env:LOCAL_RAG_RUNTIME_ROOT,
    [string]$DatabasePath = $env:LOCAL_RAG_DATABASE,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [ValidateRange(5, 300)][int]$StartupTimeoutSeconds = 45,
    [string]$PythonExecutable,
    [string]$NpmPath,
    [switch]$FromCmd
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "local_runtime.ps1")

$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$frontendRoot = Join-Path $projectRoot "frontend"
$pythonPath = ""
$mutex = $null
$context = $null
$launchId = [guid]::NewGuid().ToString("N")
$startedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
$startedServices = New-Object System.Collections.ArrayList
$launchedProcesses = New-Object System.Collections.ArrayList
$logRoot = Join-Path $projectRoot "logs"

function Get-DatabaseStatus {
    param([Parameter(Mandatory = $true)]$RuntimeContext)

    $statusJson = & $pythonPath `
        (Join-Path $projectRoot "scripts\prepare_local_database.py") `
        status `
        --database ([string]$RuntimeContext.database_path)
    if ($LASTEXITCODE -ne 0) {
        throw "无法检查数据库结构：$($RuntimeContext.database_path)"
    }
    return $statusJson | ConvertFrom-Json
}

function Wait-BackendReady {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $ready = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/health/ready" `
                -TimeoutSec 3
            if ($ready.data.status -eq "ready") {
                return
            }
            $lastError = "status=$($ready.data.status)"
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 300
    }
    throw "后端健康检查未就绪：$lastError。日志：$logRoot"
}

function New-LaunchState {
    param(
        [Parameter(Mandatory = $true)][string]$Phase,
        [Parameter(Mandatory = $true)]$RuntimeContext
    )

    return [ordered]@{
        schema_version = 2
        launch_id = $launchId
        phase = $Phase
        project_root = $projectRoot
        runtime_root = [string]$RuntimeContext.runtime_root
        runtime_id = [string]$RuntimeContext.runtime_id
        backend_port = $BackendPort
        frontend_port = $FrontendPort
        started_at_utc = $startedAtUtc
        services = @($startedServices)
    }
}

function Get-StateService {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$Name
    )

    return $State.services |
        Where-Object { [string]$_.name -eq $Name } |
        Select-Object -First 1
}

try {
    if ($BackendPort -eq $FrontendPort) {
        throw "后端和前端端口不能相同。"
    }
    foreach ($port in @($BackendPort, $FrontendPort)) {
        if ($port -lt 1 -or $port -gt 65535) {
            throw "端口超出有效范围：$port"
        }
    }

    $context = Get-LocalRuntimeContext `
        -ProjectRoot $projectRoot `
        -RuntimeRoot $RuntimeRoot `
        -DatabasePath $DatabasePath `
        -RequireDatabase `
        -RequireRuntimeIdentity
    $logRoot = [string]$context.log_root
    $mutex = Enter-LocalLauncherMutex -Identity (
        "$projectRoot|$($context.runtime_root)"
    )

    $envPath = Join-Path $projectRoot ".env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        throw "缺少环境配置：$envPath。请先执行 Copy-Item .env.example .env 并完成配置。"
    }
    if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
    }
    else {
        $pythonPath = Resolve-LocalFullPath -Path $PythonExecutable -BasePath $projectRoot
    }
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "缺少 Python 虚拟环境：$pythonPath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules") -PathType Container)) {
        throw "缺少前端依赖。请在 frontend 目录执行 npm ci。"
    }
    if ([string]::IsNullOrWhiteSpace($NpmPath)) {
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($null -eq $npmCommand) {
            throw "找不到 npm.cmd。请安装 Node.js 20.19+ 或 22.12+，并重新打开终端。"
        }
        $resolvedNpmPath = [string]$npmCommand.Source
    }
    else {
        $resolvedNpmPath = Resolve-LocalFullPath -Path $NpmPath -BasePath $projectRoot
        if (-not (Test-Path -LiteralPath $resolvedNpmPath -PathType Leaf)) {
            throw "指定的 npm 命令不存在：$resolvedNpmPath"
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "run.py") -PathType Leaf)) {
        throw "缺少后端入口：$(Join-Path $projectRoot 'run.py')"
    }

    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    Write-Host "项目目录：$projectRoot"
    Write-Host "固定数据目录：$($context.runtime_root)"
    Write-Host "数据库：$($context.database_path)"
    if (-not [string]::IsNullOrWhiteSpace([string]$context.runtime_id)) {
        Write-Host "Runtime ID：$($context.runtime_id)"
    }

    $existingState = $null
    if (Test-Path -LiteralPath $context.state_path -PathType Leaf) {
        $existingState = Read-LocalJsonFile -Path $context.state_path
        if (-not (Test-LocalLaunchStateMatchesContext -State $existingState -Context $context)) {
            throw "启动状态属于其他项目或运行时，已拒绝覆盖：$($context.state_path)"
        }
        $existingBackend = Get-StateService -State $existingState -Name "backend"
        $existingFrontend = Get-StateService -State $existingState -Name "frontend"
        if (
            $null -ne $existingBackend -and
            $null -ne $existingFrontend -and
            (Test-LocalServiceRunning -Service $existingBackend) -and
            (Test-LocalServiceRunning -Service $existingFrontend)
        ) {
            Wait-BackendReady -Port ([int]$existingBackend.port) -TimeoutSeconds 10
            Write-Host "项目已经运行，无需重复启动。"
            Write-Host "访问地址：http://127.0.0.1:$($existingFrontend.port)/"
            if (-not $NoBrowser) {
                Start-Process "http://127.0.0.1:$($existingFrontend.port)/"
            }
            return
        }
        Write-Warning "检测到陈旧或不完整的本项目启动状态，将在确认端口安全后重新启动。"
        $staleStoppedIds = New-Object 'System.Collections.Generic.HashSet[int]'
        $staleServices = @($existingState.services)
        for ($index = $staleServices.Count - 1; $index -ge 0; $index -= 1) {
            Stop-LocalServiceRecord `
                -Service $staleServices[$index] `
                -StoppedIds $staleStoppedIds
        }
    }

    foreach ($portInfo in @(
        [pscustomobject]@{ port = $BackendPort; name = "后端" },
        [pscustomobject]@{ port = $FrontendPort; name = "前端" }
    )) {
        $owner = Get-LocalListeningProcessId -Port ([int]$portInfo.port)
        if ($null -ne $owner) {
            throw (
                "$($portInfo.name)端口 $($portInfo.port) 已被 PID $owner 占用。" +
                "启动器不会终止未知进程；请更换端口或自行处理占用。"
            )
        }
    }

    $databaseStatus = Get-DatabaseStatus -RuntimeContext $context
    if ($databaseStatus.upgrade_required) {
        Write-Host ""
        Write-Host "数据库需要更新：$($databaseStatus.current) -> $($databaseStatus.head)"
        Write-Host "备份目录：$($context.backup_root)"
        $shouldUpgrade = $AutoUpgrade
        if (-not $shouldUpgrade) {
            $confirmation = Read-Host "备份并更新数据库后继续？[y/N]"
            $shouldUpgrade = $confirmation -match "^(?i:y|yes)$"
        }
        if (-not $shouldUpgrade) {
            throw "已取消数据库更新，原数据未更改。"
        }
        $upgradeJson = & $pythonPath `
            (Join-Path $projectRoot "scripts\prepare_local_database.py") `
            upgrade `
            --database ([string]$context.database_path) `
            --backup-dir ([string]$context.backup_root)
        if ($LASTEXITCODE -ne 0) {
            throw "数据库更新失败，原数据库未被替换。"
        }
        $upgradeResult = $upgradeJson | ConvertFrom-Json
        Write-Host "数据库更新完成。备份：$($upgradeResult.backup)"
    }

    $databaseUrlPath = ([string]$context.database_path).Replace("\", "/")
    $env:DATABASE_URL = "sqlite:///$databaseUrlPath"
    $env:DATA_DIR = [string]$context.runtime_root
    $env:METADATA_DIR = Join-Path $context.runtime_root "metadata"
    $env:UPLOAD_DIR = Join-Path $context.runtime_root "uploads"
    $env:CHROMA_DIR = Join-Path $context.runtime_root "chroma"
    $env:CHAT_HISTORY_DIR = Join-Path $context.runtime_root "chat_history"
    $env:BACKUP_DIR = Join-Path $context.runtime_root "backups"
    $env:EVALUATION_DIR = Join-Path $context.runtime_root "evaluations"
    $env:LOG_DIR = $logRoot
    $env:HOST = "127.0.0.1"
    $env:PORT = [string]$BackendPort
    $env:DEBUG = "false"
    $env:CORS_ALLOWED_ORIGINS = ConvertTo-Json -Compress @(
        "http://127.0.0.1:$FrontendPort",
        "http://localhost:$FrontendPort"
    )
    $env:VITE_API_MODE = "real"
    $env:VITE_API_BASE_URL = "http://127.0.0.1:$BackendPort"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    Write-LocalJsonAtomic `
        -Path $context.state_path `
        -Value (New-LaunchState -Phase "starting" -RuntimeContext $context)

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backendProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @("run.py") `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot "backend-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logRoot "backend-$stamp.err.log")
    $backendLaunchRecord = Get-LocalProcessSnapshot -ProcessId $backendProcess.Id
    if ($null -ne $backendLaunchRecord) {
        [void]$launchedProcesses.Add($backendLaunchRecord)
    }
    $backendPid = Wait-LocalListeningProcess `
        -Port $BackendPort `
        -ServiceName "后端" `
        -TimeoutSeconds $StartupTimeoutSeconds `
        -LauncherProcess $backendProcess `
        -LogRoot $logRoot `
        -ExpectedCommandFragment "run.py"
    $backendService = New-LocalServiceRecord `
        -Name "backend" `
        -Port $BackendPort `
        -ProcessId $backendPid `
        -LauncherProcessId $backendProcess.Id
    [void]$startedServices.Add($backendService)
    Write-LocalJsonAtomic `
        -Path $context.state_path `
        -Value (New-LaunchState -Phase "backend_started" -RuntimeContext $context)
    Wait-BackendReady -Port $BackendPort -TimeoutSeconds $StartupTimeoutSeconds

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $frontendProcess = Start-Process `
        -FilePath $resolvedNpmPath `
        -ArgumentList @(
            "run", "dev:real", "--", "--host", "127.0.0.1",
            "--port", [string]$FrontendPort, "--strictPort"
        ) `
        -WorkingDirectory $frontendRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot "frontend-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logRoot "frontend-$stamp.err.log")
    $frontendLaunchRecord = Get-LocalProcessSnapshot -ProcessId $frontendProcess.Id
    if ($null -ne $frontendLaunchRecord) {
        [void]$launchedProcesses.Add($frontendLaunchRecord)
    }
    $frontendPid = Wait-LocalListeningProcess `
        -Port $FrontendPort `
        -ServiceName "Vue Real 前端" `
        -TimeoutSeconds $StartupTimeoutSeconds `
        -LauncherProcess $frontendProcess `
        -LogRoot $logRoot `
        -ExpectedCommandFragment $frontendRoot
    $frontendService = New-LocalServiceRecord `
        -Name "frontend" `
        -Port $FrontendPort `
        -ProcessId $frontendPid `
        -LauncherProcessId $frontendProcess.Id
    [void]$startedServices.Add($frontendService)

    Write-LocalJsonAtomic `
        -Path $context.state_path `
        -Value (New-LaunchState -Phase "running" -RuntimeContext $context)

    Write-Host ""
    Write-Host "启动成功（Vue Real + FastAPI）。"
    Write-Host "访问地址：http://127.0.0.1:$FrontendPort/"
    Write-Host "日志目录：$logRoot"
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$FrontendPort/"
    }
}
catch {
    $message = $_.Exception.Message
    $stoppedIds = New-Object 'System.Collections.Generic.HashSet[int]'
    for ($index = $startedServices.Count - 1; $index -ge 0; $index -= 1) {
        Stop-LocalServiceRecord -Service $startedServices[$index] -StoppedIds $stoppedIds
    }
    for ($index = $launchedProcesses.Count - 1; $index -ge 0; $index -= 1) {
        Stop-LocalRecordedProcess `
            -Record $launchedProcesses[$index] `
            -StoppedIds $stoppedIds `
            -Label "未完成的启动进程"
    }
    if (
        $null -ne $context -and
        (Test-Path -LiteralPath $context.state_path -PathType Leaf)
    ) {
        try {
            $failedState = Read-LocalJsonFile -Path $context.state_path
            if ([string]$failedState.launch_id -eq $launchId) {
                Remove-Item -LiteralPath $context.state_path -Force
            }
        }
        catch {
            Write-Warning "无法核对失败启动的状态文件，请人工检查：$($context.state_path)"
        }
    }
    [Console]::Error.WriteLine("启动失败：$message")
    [Console]::Error.WriteLine("已回滚本次启动的进程；日志目录：$logRoot")
    [Console]::Error.WriteLine("修正提示后可直接重试，启动器不会终止端口上的未知进程。")
    Wait-LocalExplorerError -FromCmd:$FromCmd
    exit 1
}
finally {
    Exit-LocalLauncherMutex -Mutex $mutex
}

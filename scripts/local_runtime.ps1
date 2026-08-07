Set-StrictMode -Version 2.0

function Resolve-LocalFullPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$BasePath
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Test-LocalSamePath {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $leftPath = [System.IO.Path]::GetFullPath($Left).TrimEnd('\', '/')
    $rightPath = [System.IO.Path]::GetFullPath($Right).TrimEnd('\', '/')
    return [string]::Equals(
        $leftPath,
        $rightPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Read-LocalJsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding utf8 |
            ConvertFrom-Json
    }
    catch {
        throw "JSON 文件无效：$Path。$($_.Exception.Message)"
    }
}

function Write-LocalJsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )

    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporaryPath = Join-Path $directory (
        ".{0}.{1}.partial" -f ([System.IO.Path]::GetFileName($Path)),
        [guid]::NewGuid().ToString("N")
    )
    $backupPath = Join-Path $directory (
        ".{0}.{1}.replace-backup" -f ([System.IO.Path]::GetFileName($Path)),
        [guid]::NewGuid().ToString("N")
    )
    try {
        $json = $Value | ConvertTo-Json -Depth 12
        [System.IO.File]::WriteAllText(
            $temporaryPath,
            $json + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false))
        )
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            [System.IO.File]::Replace($temporaryPath, $Path, $backupPath)
            Remove-Item -LiteralPath $backupPath -Force
        }
        else {
            [System.IO.File]::Move($temporaryPath, $Path)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
        if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
            Remove-Item -LiteralPath $backupPath -Force
        }
    }
}

function Get-LocalRuntimeContext {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [string]$RuntimeRoot,
        [string]$DatabasePath,
        [switch]$RequireDatabase,
        [switch]$RequireRuntimeIdentity
    )

    $projectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
    $configPath = Join-Path $projectRoot ".local-rag-chat.json"
    $expectedRuntimeId = ""

    if (
        [string]::IsNullOrWhiteSpace($RuntimeRoot) -and
        [string]::IsNullOrWhiteSpace($DatabasePath)
    ) {
        if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
            throw (
                "缺少固定运行时配置：$configPath。请先按 README 的「首次初始化」" +
                "创建运行时，启动器不会猜测或切换数据目录。"
            )
        }
        $config = Read-LocalJsonFile -Path $configPath
        $RuntimeRoot = [string]$config.runtime_root
        $DatabasePath = [string]$config.database_path
        $expectedRuntimeId = [string]$config.runtime_id
    }

    if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        throw "显式指定 DatabasePath 时必须同时指定 RuntimeRoot。"
    }
    $resolvedRuntimeRoot = Resolve-LocalFullPath -Path $RuntimeRoot -BasePath $projectRoot
    if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
        $DatabasePath = Join-Path $resolvedRuntimeRoot "metadata\local_rag_chat.db"
    }
    $resolvedDatabasePath = Resolve-LocalFullPath -Path $DatabasePath -BasePath $projectRoot
    $markerPath = Join-Path $resolvedRuntimeRoot ".local-rag-runtime.json"
    $activeRuntimeId = ""
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        $marker = Read-LocalJsonFile -Path $markerPath
        $activeRuntimeId = [string]$marker.runtime_id
    }

    if (-not [string]::IsNullOrWhiteSpace($expectedRuntimeId)) {
        if ([string]::IsNullOrWhiteSpace($activeRuntimeId)) {
            throw "缺少固定运行时身份文件：$markerPath"
        }
        if ($activeRuntimeId -ne $expectedRuntimeId) {
            throw (
                "固定运行时身份不匹配。期望 $expectedRuntimeId，实际 " +
                "$activeRuntimeId；已拒绝操作。"
            )
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace($activeRuntimeId)) {
        $expectedRuntimeId = $activeRuntimeId
    }
    if ($RequireRuntimeIdentity -and [string]::IsNullOrWhiteSpace($activeRuntimeId)) {
        throw "缺少固定运行时身份文件：$markerPath"
    }

    if ($RequireDatabase -and -not (
        Test-Path -LiteralPath $resolvedDatabasePath -PathType Leaf
    )) {
        throw "本地数据库不存在：$resolvedDatabasePath"
    }

    return [pscustomobject][ordered]@{
        project_root = $projectRoot
        config_path = $configPath
        runtime_root = $resolvedRuntimeRoot
        database_path = $resolvedDatabasePath
        runtime_id = $expectedRuntimeId
        marker_path = $markerPath
        state_path = Join-Path $resolvedRuntimeRoot ".local-rag-launch-state.json"
        log_root = Join-Path $resolvedRuntimeRoot "logs"
        backup_root = Join-Path $resolvedRuntimeRoot "backups\startup-migrations"
    }
}

function Get-LocalListeningProcessId {
    param([Parameter(Mandatory = $true)][int]$Port)

    $connection = Get-NetTCPConnection `
        -State Listen `
        -LocalPort $Port `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $connection) {
        return $null
    }
    return [int]$connection.OwningProcess
}

function Test-LocalProcessDescendantOf {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][int]$AncestorProcessId
    )

    if ($ProcessId -eq $AncestorProcessId) {
        return $true
    }
    $currentId = $ProcessId
    for ($depth = 0; $depth -lt 16; $depth += 1) {
        $process = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $currentId" `
            -ErrorAction SilentlyContinue
        if ($null -eq $process -or [int]$process.ParentProcessId -le 0) {
            return $false
        }
        $parentId = [int]$process.ParentProcessId
        if ($parentId -eq $AncestorProcessId) {
            return $true
        }
        $currentId = $parentId
    }
    return $false
}

function Wait-LocalListeningProcess {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [System.Diagnostics.Process]$LauncherProcess,
        [Parameter(Mandatory = $true)][string]$LogRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedCommandFragment
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $owner = Get-LocalListeningProcessId -Port $Port
        if ($null -ne $owner) {
            if (
                $null -eq $LauncherProcess -or
                -not (Test-LocalProcessDescendantOf `
                    -ProcessId ([int]$owner) `
                    -AncestorProcessId $LauncherProcess.Id)
            ) {
                throw (
                    "$ServiceName 启动期间端口 $Port 被非本次启动的 PID $owner 占用；" +
                    "已拒绝接管。"
                )
            }
            $ownerSnapshot = Get-LocalProcessSnapshot -ProcessId ([int]$owner)
            if (
                $null -eq $ownerSnapshot -or
                ([string]$ownerSnapshot.command_line).IndexOf(
                    $ExpectedCommandFragment,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -lt 0
            ) {
                throw "$ServiceName 监听进程身份与项目目录不匹配；已拒绝接管 PID $owner。"
            }
            return [int]$owner
        }
        if ($null -ne $LauncherProcess) {
            $LauncherProcess.Refresh()
            if ($LauncherProcess.HasExited) {
                $exitCodeText = "unknown"
                try {
                    $candidateExitCode = [string]$LauncherProcess.ExitCode
                    if (-not [string]::IsNullOrWhiteSpace($candidateExitCode)) {
                        $exitCodeText = $candidateExitCode
                    }
                }
                catch { }
                throw (
                    "$ServiceName 启动进程提前退出（退出码 " +
                    "$exitCodeText）。日志：$LogRoot"
                )
            }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$ServiceName 启动超时。日志：$LogRoot"
}

function Get-LocalProcessSnapshot {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $nativeProcess = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId = $ProcessId" `
        -ErrorAction SilentlyContinue
    if ($null -eq $nativeProcess) {
        return $null
    }
    $managedProcess = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $managedProcess) {
        return $null
    }
    try {
        $startTime = $managedProcess.StartTime.ToUniversalTime().ToString("o")
    }
    catch {
        return $null
    }
    return [pscustomobject][ordered]@{
        process_id = [int]$ProcessId
        start_time_utc = $startTime
        executable_path = [string]$nativeProcess.ExecutablePath
        command_line = [string]$nativeProcess.CommandLine
    }
}

function New-LocalServiceRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [int]$LauncherProcessId = 0
    )

    $process = Get-LocalProcessSnapshot -ProcessId $ProcessId
    if ($null -eq $process) {
        throw "无法记录 $Name 进程身份：PID $ProcessId"
    }
    $launcher = $null
    if ($LauncherProcessId -gt 0 -and $LauncherProcessId -ne $ProcessId) {
        $launcher = Get-LocalProcessSnapshot -ProcessId $LauncherProcessId
    }
    return [pscustomobject][ordered]@{
        name = $Name
        port = $Port
        process = $process
        launcher = $launcher
    }
}

function Get-LocalProcessIdentityStatus {
    param([Parameter(Mandatory = $true)]$Record)

    if ($null -eq $Record -or $null -eq $Record.process_id) {
        return [pscustomobject]@{ matches = $false; running = $false; reason = "missing_record" }
    }
    $current = Get-LocalProcessSnapshot -ProcessId ([int]$Record.process_id)
    if ($null -eq $current) {
        return [pscustomobject]@{ matches = $false; running = $false; reason = "not_running" }
    }
    if ([string]$current.start_time_utc -ne [string]$Record.start_time_utc) {
        return [pscustomobject]@{ matches = $false; running = $true; reason = "pid_reused" }
    }
    if (
        -not [string]::IsNullOrWhiteSpace([string]$Record.executable_path) -and
        -not [string]::Equals(
            [string]$current.executable_path,
            [string]$Record.executable_path,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        return [pscustomobject]@{ matches = $false; running = $true; reason = "executable_changed" }
    }
    if ([string]$current.command_line -ne [string]$Record.command_line) {
        return [pscustomobject]@{ matches = $false; running = $true; reason = "command_changed" }
    }
    return [pscustomobject]@{ matches = $true; running = $true; reason = "match" }
}

function Test-LocalServiceRunning {
    param([Parameter(Mandatory = $true)]$Service)

    $identity = Get-LocalProcessIdentityStatus -Record $Service.process
    if (-not $identity.matches) {
        return $false
    }
    $portOwner = Get-LocalListeningProcessId -Port ([int]$Service.port)
    return $null -ne $portOwner -and [int]$portOwner -eq [int]$Service.process.process_id
}

function Stop-LocalRecordedProcess {
    param(
        $Record,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.HashSet[int]]$StoppedIds,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($null -eq $Record -or $null -eq $Record.process_id) {
        return
    }
    $processId = [int]$Record.process_id
    if ($StoppedIds.Contains($processId)) {
        return
    }
    $identity = Get-LocalProcessIdentityStatus -Record $Record
    if (-not $identity.running) {
        Write-Host "$Label 已停止（PID $processId）。"
        [void]$StoppedIds.Add($processId)
        return
    }
    if (-not $identity.matches) {
        Write-Warning (
            "$Label 的 PID $processId 已被其他进程复用或身份改变（$($identity.reason)），" +
            "为避免误杀已跳过。"
        )
        [void]$StoppedIds.Add($processId)
        return
    }
    Stop-Process -Id $processId -Force -ErrorAction Stop
    try {
        Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
    }
    catch {
        # PowerShell 5.1 在进程已退出时可能抛出异常；身份已在终止前校验。
    }
    Write-Host "$Label 已停止（PID $processId）。"
    [void]$StoppedIds.Add($processId)
}

function Stop-LocalServiceRecord {
    param(
        $Service,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.HashSet[int]]$StoppedIds
    )

    if ($null -eq $Service) {
        return
    }
    Stop-LocalRecordedProcess `
        -Record $Service.process `
        -StoppedIds $StoppedIds `
        -Label ([string]$Service.name)
    Stop-LocalRecordedProcess `
        -Record $Service.launcher `
        -StoppedIds $StoppedIds `
        -Label ("{0} 启动器" -f [string]$Service.name)
}

function Test-LocalLaunchStateMatchesContext {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)]$Context
    )

    if ($null -eq $State) {
        return $false
    }
    foreach ($requiredProperty in @("schema_version", "project_root", "runtime_id", "services")) {
        if ($null -eq $State.PSObject.Properties[$requiredProperty]) {
            return $false
        }
    }
    if ([int]$State.schema_version -ne 2) {
        return $false
    }
    if (-not (Test-LocalSamePath -Left ([string]$State.project_root) -Right ([string]$Context.project_root))) {
        return $false
    }
    if (
        -not [string]::IsNullOrWhiteSpace([string]$Context.runtime_id) -and
        [string]$State.runtime_id -ne [string]$Context.runtime_id
    ) {
        return $false
    }
    return $true
}

function Enter-LocalLauncherMutex {
    param([Parameter(Mandatory = $true)][string]$Identity)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Identity.ToLowerInvariant())
        $hash = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
    $mutex = New-Object System.Threading.Mutex($false, "Local\LocalRagChat-$hash")
    if (-not $mutex.WaitOne([TimeSpan]::FromSeconds(15))) {
        $mutex.Dispose()
        throw "另一个启动或停止操作仍在进行，请稍后重试。"
    }
    return $mutex
}

function Exit-LocalLauncherMutex {
    param([System.Threading.Mutex]$Mutex)

    if ($null -ne $Mutex) {
        try { $Mutex.ReleaseMutex() } catch { }
        $Mutex.Dispose()
    }
}

function Test-LocalStartedFromExplorer {
    try {
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $PID"
        $parent = Get-CimInstance Win32_Process -Filter (
            "ProcessId = {0}" -f [int]$current.ParentProcessId
        )
        if ([string]$parent.Name -notmatch '^(cmd|conhost)\.exe$') {
            return $false
        }
        $grandParent = Get-CimInstance Win32_Process -Filter (
            "ProcessId = {0}" -f [int]$parent.ParentProcessId
        )
        return [string]$grandParent.Name -ieq "explorer.exe"
    }
    catch {
        return $false
    }
}

function Wait-LocalExplorerError {
    param([switch]$FromCmd)

    if ($FromCmd -and (Test-LocalStartedFromExplorer)) {
        Write-Host ""
        Read-Host "按 Enter 键关闭窗口"
    }
}

param(
    [string]$RuntimeRoot = $env:LOCAL_RAG_RUNTIME_ROOT,
    [string]$DatabasePath = $env:LOCAL_RAG_DATABASE,
    [switch]$FromCmd
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "local_runtime.ps1")

$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$mutex = $null

try {
    $context = Get-LocalRuntimeContext `
        -ProjectRoot $projectRoot `
        -RuntimeRoot $RuntimeRoot `
        -DatabasePath $DatabasePath
    $mutex = Enter-LocalLauncherMutex -Identity (
        "$projectRoot|$($context.runtime_root)"
    )

    if (-not (Test-Path -LiteralPath $context.state_path -PathType Leaf)) {
        Write-Host "项目已经停止（没有启动状态文件）。"
        exit 0
    }

    $state = Read-LocalJsonFile -Path $context.state_path
    if (-not (Test-LocalLaunchStateMatchesContext -State $state -Context $context)) {
        throw "启动状态属于其他项目或运行时，已拒绝停止：$($context.state_path)"
    }

    $stoppedIds = New-Object 'System.Collections.Generic.HashSet[int]'
    $services = @($state.services)
    for ($index = $services.Count - 1; $index -ge 0; $index -= 1) {
        Stop-LocalServiceRecord -Service $services[$index] -StoppedIds $stoppedIds
    }

    if (Test-Path -LiteralPath $context.state_path -PathType Leaf) {
        Remove-Item -LiteralPath $context.state_path -Force
    }
    Write-Host "项目停止完成。只处理了身份匹配的本项目记录进程。"
    exit 0
}
catch {
    [Console]::Error.WriteLine("停止失败：$($_.Exception.Message)")
    [Console]::Error.WriteLine("未按端口终止任何未知进程。")
    Wait-LocalExplorerError -FromCmd:$FromCmd
    exit 1
}
finally {
    Exit-LocalLauncherMutex -Mutex $mutex
}

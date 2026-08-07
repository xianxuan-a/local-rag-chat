param(
    [string]$RuntimeRoot = $env:LOCAL_RAG_RUNTIME_ROOT,
    [string]$DatabasePath = $env:LOCAL_RAG_DATABASE,
    [switch]$FromCmd
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "local_runtime.ps1")

$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))

try {
    $context = Get-LocalRuntimeContext `
        -ProjectRoot $projectRoot `
        -RuntimeRoot $RuntimeRoot `
        -DatabasePath $DatabasePath
    Write-Host "项目目录：$projectRoot"
    Write-Host "固定数据目录：$($context.runtime_root)"

    if (-not (Test-Path -LiteralPath $context.state_path -PathType Leaf)) {
        Write-Host "状态：已停止（没有启动状态文件）"
        exit 3
    }

    $state = Read-LocalJsonFile -Path $context.state_path
    if (-not (Test-LocalLaunchStateMatchesContext -State $state -Context $context)) {
        throw "启动状态属于其他项目或运行时：$($context.state_path)"
    }

    $services = @($state.services)
    $serviceNames = @($services | ForEach-Object { [string]$_.name })
    $allRunning = (
        $services.Count -eq 2 -and
        $serviceNames -contains "backend" -and
        $serviceNames -contains "frontend"
    )
    foreach ($service in $services) {
        $identity = Get-LocalProcessIdentityStatus -Record $service.process
        $portOwner = Get-LocalListeningProcessId -Port ([int]$service.port)
        $ownsPort = (
            $null -ne $portOwner -and
            [int]$portOwner -eq [int]$service.process.process_id
        )
        if ($identity.matches -and $ownsPort) {
            Write-Host (
                "{0}：运行中，PID {1}，端口 {2}" -f
                [string]$service.name,
                [int]$service.process.process_id,
                [int]$service.port
            )
        }
        else {
            $allRunning = $false
            $ownerText = if ($null -eq $portOwner) { "空闲" } else { "PID $portOwner" }
            Write-Warning (
                "{0}：未运行或身份不匹配（记录 PID {1}，原因 {2}，端口 {3} 为 {4}）" -f
                [string]$service.name,
                [int]$service.process.process_id,
                [string]$identity.reason,
                [int]$service.port,
                $ownerText
            )
        }
    }

    if ($allRunning -and [string]$state.phase -eq "running") {
        Write-Host "状态：运行中"
        Write-Host "访问地址：http://127.0.0.1:$($state.frontend_port)/"
        exit 0
    }
    Write-Host "状态：已停止、启动未完成或状态陈旧"
    exit 3
}
catch {
    [Console]::Error.WriteLine("状态检查失败：$($_.Exception.Message)")
    Wait-LocalExplorerError -FromCmd:$FromCmd
    exit 1
}

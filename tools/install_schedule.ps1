param(
    [string]$Environment = 'github-stars',
    [string]$TaskName = 'GitHub Stars++',
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$entry = Join-Path $PSScriptRoot 'entry.py'
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne "GitHub Stars++ hourly check: $projectRoot") {
    throw '同名计划任务不属于当前源码目录，停止覆盖。请使用不同 TaskName。'
}
if ($Remove) {
    if ($existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    Write-Output '计划任务已移除；环境、设置与数据保留。'
    exit 0
}
$raw = & conda run -n $Environment --no-capture-output python -s $entry --check-environment
if ($LASTEXITCODE -ne 0) { throw 'Conda 环境检查失败，请先按 README 安装。' }
$info = ($raw -join "`n") | ConvertFrom-Json
if (-not $info.valid -or $info.environment -ne $Environment) { throw '实际环境与指定环境不符。' }
$pythonw = Join-Path (Split-Path -Parent $info.python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw '目标环境缺少 pythonw.exe。' }
$arguments = '-s "' + $entry + '" --root "' + $projectRoot + '" tick'
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $projectRoot
$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Hours 1)
$logon = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($hourly,$logon) -Settings $settings -Principal $principal -Description "GitHub Stars++ hourly check: $projectRoot" -Force | Select-Object TaskName,State
Write-Output '已安装：每小时检查一次到期任务，登录后补当前周期。默认每日 09:00 采集，周五 19:00 生成周报；未登录、关机时不运行。'

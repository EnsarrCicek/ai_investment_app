<#
Momentum prospective collection - make the existing scheduled tasks run WITHOUT a visible console window.

Changes ONLY the action of MomentumProspectiveProbe / MomentumProspectiveEOD:
  cmd.exe ...  ->  wscript.exe //B //NoLogo scripts\run_hidden_momentum_task.vbs <probe|eod>
The launched command line, working directory, log files, triggers, retries, time limits and principal are unchanged,
and no data/store file is touched. The previous task definitions are exported as XML first (rollback:
Register-ScheduledTask -Xml (Get-Content <backup> -Raw) -TaskName <name> -Force).

Note: re-running install_momentum_collection_tasks.ps1 restores the visible cmd.exe action; run this script after it.

Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File hide_momentum_task_windows.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File hide_momentum_task_windows.ps1
#>
param(
    [switch]$DryRun,
    [string]$BackendDir = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$BackendDir = (Resolve-Path $BackendDir).Path
$Vbs = Join-Path $BackendDir "scripts\run_hidden_momentum_task.vbs"
$Wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
$BackupDir = Join-Path $BackendDir "app\research\momentum_collector\store\task_backups"
if (-not (Test-Path $Vbs)) { throw "launcher not found: $Vbs" }

$map = [ordered]@{ "MomentumProspectiveProbe" = "probe"; "MomentumProspectiveEOD" = "eod" }
foreach ($name in $map.Keys) {
    $task = Get-ScheduledTask -TaskName $name
    $argument = '//B //NoLogo "' + $Vbs + '" ' + $map[$name]
    $before = $task.Actions | ForEach-Object { $_.Execute + " " + $_.Arguments }
    Write-Host ("{0}`n  before: {1}`n  after : {2} {3}`n  cwd   : {4}" -f $name, ($before -join " | "), $Wscript, $argument, $BackendDir)
    if ($DryRun) { continue }
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $stamp = (Get-Date).ToString("yyyyMMddTHHmmss")
    Export-ScheduledTask -TaskName $name | Out-File -Encoding utf8 (Join-Path $BackupDir "$name.$stamp.xml")
    $action = New-ScheduledTaskAction -Execute $Wscript -Argument $argument -WorkingDirectory $BackendDir
    Set-ScheduledTask -TaskName $name -Action $action | Out-Null
    Write-Host "  updated (backup: $BackupDir\$name.$stamp.xml)"
}
if ($DryRun) { Write-Host "DRY RUN: no scheduled task was changed." }

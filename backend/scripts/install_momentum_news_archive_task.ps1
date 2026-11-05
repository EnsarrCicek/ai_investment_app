<#
Momentum prospective NEWS archive - Windows Task Scheduler task (research only, raw collection, no Firestore).

Creates/updates ONE task for the CURRENT user; the Yahoo tasks (MomentumProspectiveProbe / MomentumProspectiveEOD)
are never touched:
  MomentumProspectiveNewsArchive : weekdays, every 5 min from 09:30 to 18:40 (machine-local time, must be
                                   Turkey Standard Time = Europe/Istanbul) + one catch-up trigger at 19:10.
Each invocation makes exactly ONE Foreks RSS request (no Google/Yahoo per-symbol requests), singleton-locked in
Python (SKIPPED_ALREADY_RUNNING -> exit 0). Hidden launcher: wscript + run_hidden_news_archive_task.vbs, which runs
  .venv\Scripts\python.exe -X utf8 -m app.research.momentum_sources.news_archive.archiver run --sources foreks
in the backend directory and appends stdout/stderr to store\logs\task_news_stdout.log.

Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File install_momentum_news_archive_task.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File install_momentum_news_archive_task.ps1
#>
param(
    [switch]$DryRun,
    [switch]$Json,
    [string]$BackendDir = (Split-Path -Parent $PSScriptRoot),
    [string]$StartDate = (Get-Date).ToString("yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"
$BackendDir = (Resolve-Path $BackendDir).Path
$TaskName = "MomentumProspectiveNewsArchive"
$Protected = @("MomentumProspectiveProbe", "MomentumProspectiveEOD")
$LogDir = Join-Path $BackendDir "app\research\momentum_sources\store\logs"
$Python = Join-Path $BackendDir ".venv\Scripts\python.exe"
$Vbs = Join-Path $BackendDir "scripts\run_hidden_news_archive_task.vbs"
$Wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
$Command = ".venv\Scripts\python.exe -X utf8 -m app.research.momentum_sources.news_archive.archiver run --sources foreks"
$Days = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
$WindowStart = "09:30"
$WindowEnd = "18:40"
$CadenceMinutes = 5
$CatchUp = "19:10"
$Tz = (Get-TimeZone).Id

if ($TaskName -in $Protected) { throw "refusing to manage a Yahoo collector task" }

$plan = [ordered]@{
    name = $TaskName
    execute = $Wscript
    argument = '//B //NoLogo "' + $Vbs + '"'
    command = $Command
    working_directory = $BackendDir
    stdout_log = (Join-Path $LogDir "task_news_stdout.log")
    machine_time_zone = $Tz
    days = $Days
    window = "$WindowStart-$WindowEnd (machine-local, weekdays)"
    cadence_minutes = $CadenceMinutes
    repetition_duration = "09:10"
    catch_up_trigger = "$CatchUp (weekdays)"
    start_date = $StartDate
    settings = [ordered]@{
        StartWhenAvailable = $true
        MultipleInstances = "IgnoreNew"
        RestartCount = 2
        RestartIntervalMinutes = 1
        ExecutionTimeLimitMinutes = 4
        AllowStartIfOnBatteries = $true
        DontStopIfGoingOnBatteries = $true
    }
    principal = "$env:USERDOMAIN\$env:USERNAME (Interactive: runs while this user is logged on)"
    untouched_tasks = $Protected
}

if ($DryRun) {
    if ($Json) { $plan | ConvertTo-Json -Depth 6 } else { [pscustomobject]$plan | Format-List }
    Write-Host "DRY RUN: no scheduled task was created or changed."
    exit 0
}

if ($Tz -ne "Turkey Standard Time") { throw "machine time zone is '$Tz'; expected 'Turkey Standard Time'" }
if (-not (Test-Path $Python)) { throw "python not found: $Python" }
if (-not (Test-Path $Vbs)) { throw "launcher not found: $Vbs" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$action = New-ScheduledTaskAction -Execute $Wscript -Argument $plan.argument -WorkingDirectory $BackendDir
$at = [datetime]::ParseExact($StartDate + " " + $WindowStart, "yyyy-MM-dd HH:mm", [Globalization.CultureInfo]::InvariantCulture)
$main = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -WeeksInterval 1 -At $at
$rep = New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval (New-TimeSpan -Minutes $CadenceMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours 9 -Minutes 10)
$main.Repetition = $rep.Repetition
$catch = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -WeeksInterval 1 `
    -At ([datetime]::ParseExact($StartDate + " " + $CatchUp, "yyyy-MM-dd HH:mm", [Globalization.CultureInfo]::InvariantCulture))
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Description "Momentum prospective news archive: one Foreks RSS request per run (research only, no Firestore)." `
    -Action $action -Trigger @($main, $catch) -Settings $settings -Principal $principal -Force | Out-Null
Write-Host ("registered: " + $TaskName)

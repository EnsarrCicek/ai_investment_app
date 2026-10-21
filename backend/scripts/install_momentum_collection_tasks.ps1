<#
Momentum prospective collection - Windows Task Scheduler task definitions (research only).

Creates/updates two tasks for the CURRENT user. It does not change study/config semantics:
  MomentumProspectiveProbe : weekdays, every 5 min from 09:55 to 18:30 (local time = Europe/Istanbul),
                             runs one probe round and exits (one-shot, singleton-locked in Python).
  MomentumProspectiveEOD   : weekdays at 19:00 plus retry triggers 19:15 / 19:30 / 19:45; a retry is a no-op
                             when a verified EOD already completed that day (idempotent storage).
First trigger: -StartDate (default 2026-10-22). Nothing runs before it.

Usage (from any directory):
  powershell -NoProfile -ExecutionPolicy Bypass -File install_momentum_collection_tasks.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File install_momentum_collection_tasks.ps1
#>
param(
    [switch]$DryRun,
    [switch]$Json,
    [string]$BackendDir = (Split-Path -Parent $PSScriptRoot),
    [string]$LogDir = "",
    [string]$StartDate = "2026-10-22"
)

$ErrorActionPreference = "Stop"
$BackendDir = (Resolve-Path $BackendDir).Path
if (-not $LogDir) { $LogDir = Join-Path $BackendDir "app\research\momentum_collector\store\logs" }
$Python = Join-Path $BackendDir ".venv\Scripts\python.exe"
$Days = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
$Start = [datetime]::ParseExact($StartDate, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture)

function New-TaskArgument([string]$Command) {
    # cmd /s /c "<line>": outer quotes stripped, inner quotes keep paths with spaces intact; stdout+stderr appended.
    $log = Join-Path $LogDir ("task_" + $Command + "_stdout.log")
    return '/d /s /c ""' + $Python + '" -X utf8 scripts\momentum_collect.py ' + $Command + ' >> "' + $log + '" 2>&1"'
}

$tasks = @(
    [ordered]@{
        name = "MomentumProspectiveProbe"
        description = "Momentum prospective study: one visibility probe round (research only, no Firestore)."
        command = "probe"
        times = @("09:55")
        repetition_minutes = 5
        repetition_duration = "08:35"
        window = "09:55-18:30 Europe/Istanbul, weekdays"
        execution_time_limit_minutes = 4
        restart_count = 1
        restart_interval_minutes = 1
    },
    [ordered]@{
        name = "MomentumProspectiveEOD"
        description = "Momentum prospective study: end-of-day archive + integrity check (research only, no Firestore)."
        command = "eod"
        times = @("19:00", "19:15", "19:30", "19:45")
        repetition_minutes = 0
        repetition_duration = ""
        window = "weekdays 19:00 + 3 retries at 15 min (no-op after a verified EOD)"
        execution_time_limit_minutes = 60
        restart_count = 3
        restart_interval_minutes = 15
    }
)

$plan = foreach ($t in $tasks) {
    [ordered]@{
        name = $t.name
        execute = "cmd.exe"
        argument = New-TaskArgument $t.command
        working_directory = $BackendDir
        python = $Python
        log_dir = $LogDir
        days = $Days
        start_boundary = ($Start.ToString("yyyy-MM-dd") + "T" + $t.times[0])
        trigger_times = $t.times
        repetition_minutes = $t.repetition_minutes
        repetition_duration = $t.repetition_duration
        window = $t.window
        settings = [ordered]@{
            StartWhenAvailable = $true
            MultipleInstances = "IgnoreNew"
            RestartCount = $t.restart_count
            RestartIntervalMinutes = $t.restart_interval_minutes
            ExecutionTimeLimitMinutes = $t.execution_time_limit_minutes
            AllowStartIfOnBatteries = $true
            DontStopIfGoingOnBatteries = $true
        }
        principal = "$env:USERDOMAIN\$env:USERNAME (Interactive: runs while this user is logged on)"
    }
}

if ($DryRun) {
    if ($Json) { $plan | ConvertTo-Json -Depth 6 } else { $plan | ForEach-Object { [pscustomobject]$_ } | Format-List }
    Write-Host "DRY RUN: no scheduled task was created or changed."
    exit 0
}

if (-not (Test-Path $Python)) { throw "python not found: $Python" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

foreach ($t in $tasks) {
    $p = $plan | Where-Object { $_.name -eq $t.name }
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $p.argument -WorkingDirectory $BackendDir
    $triggers = foreach ($hm in $t.times) {
        $at = [datetime]::ParseExact($StartDate + " " + $hm, "yyyy-MM-dd HH:mm", [Globalization.CultureInfo]::InvariantCulture)
        $trg = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -WeeksInterval 1 -At $at
        if ($t.repetition_minutes -gt 0) {
            $parts = $t.repetition_duration.Split(":")
            $rep = New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval (New-TimeSpan -Minutes $t.repetition_minutes) `
                -RepetitionDuration (New-TimeSpan -Hours ([int]$parts[0]) -Minutes ([int]$parts[1]))
            $trg.Repetition = $rep.Repetition
        }
        $trg
    }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -RestartCount $t.restart_count -RestartInterval (New-TimeSpan -Minutes $t.restart_interval_minutes) `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $t.execution_time_limit_minutes) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $t.name -Description $t.description -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host ("registered: " + $t.name)
}

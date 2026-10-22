' Momentum prospective collection - hidden launcher (research only).
' Runs exactly the same command line as install_momentum_collection_tasks.ps1, but with no visible console window:
'   cmd /d /s /c ""<backend>\.venv\Scripts\python.exe" -X utf8 scripts\momentum_collect.py <command> >> "<log>" 2>&1"
' The Python exit code is returned to Task Scheduler (Last Run Result). Usage:
'   wscript.exe //B //NoLogo run_hidden_momentum_task.vbs probe|eod|ping
Option Explicit

Dim fso, sh, cmd, backend, logDir, python, line, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

If WScript.Arguments.Count <> 1 Then WScript.Quit 64
cmd = LCase(WScript.Arguments(0))
If cmd <> "probe" And cmd <> "eod" And cmd <> "ping" Then WScript.Quit 64

backend = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
logDir = backend & "\app\research\momentum_collector\store\logs"
python = backend & "\.venv\Scripts\python.exe"
If Not fso.FileExists(python) Then WScript.Quit 65
If Not fso.FolderExists(logDir) Then WScript.Quit 66

sh.CurrentDirectory = backend
line = "cmd.exe /d /s /c """"" & python & """ -X utf8 scripts\momentum_collect.py " & cmd & _
       " >> """ & logDir & "\task_" & cmd & "_stdout.log"" 2>&1"""
rc = sh.Run(line, 0, True)
WScript.Quit rc

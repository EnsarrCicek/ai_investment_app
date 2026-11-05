' Momentum prospective NEWS archive - hidden launcher (research only, raw collection).
' Runs, with no visible console window:
'   cmd /d /s /c ""<backend>\.venv\Scripts\python.exe" -X utf8 -m app.research.momentum_sources.news_archive.archiver run --sources foreks >> "<log>" 2>&1"
' The Python exit code is returned to Task Scheduler (Last Run Result). Usage:
'   wscript.exe //B //NoLogo run_hidden_news_archive_task.vbs
Option Explicit

Dim fso, sh, backend, logDir, python, line, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

backend = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
logDir = backend & "\app\research\momentum_sources\store\logs"
python = backend & "\.venv\Scripts\python.exe"
If Not fso.FileExists(python) Then WScript.Quit 65
If Not fso.FolderExists(logDir) Then WScript.Quit 66

sh.CurrentDirectory = backend
line = "cmd.exe /d /s /c """"" & python & """ -X utf8 -m app.research.momentum_sources.news_archive.archiver run --sources foreks" & _
       " >> """ & logDir & "\task_news_stdout.log"" 2>&1"""
rc = sh.Run(line, 0, True)
WScript.Quit rc

$ErrorActionPreference='Stop'
$projectDir=Split-Path -Parent $PSScriptRoot
$backupDir=Join-Path $projectDir 'backups'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$pythonPath=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if(!(Test-Path -LiteralPath $pythonPath)){$pythonPath=(Get-Command python).Source}
$backupPath=Join-Path $backupDir ('assessment-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.sqlite3')
& $pythonPath -c 'import sqlite3,sys; a=sqlite3.connect(sys.argv[1]); b=sqlite3.connect(sys.argv[2]); a.backup(b); b.close(); a.close()' (Join-Path $projectDir 'backend/assessment.sqlite3') $backupPath
if($LASTEXITCODE -ne 0){throw '備份失敗。'}
Write-Output "備份完成：$backupPath"

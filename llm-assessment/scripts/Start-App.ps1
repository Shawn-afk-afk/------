param([int]$Port=8765,[switch]$PublicHttps,[string]$PythonPath='')
$ErrorActionPreference='Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectDir '.runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
if (!$PythonPath) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $PythonPath=$bundledPython }
    else { $PythonPath=(Get-Command python -ErrorAction Stop).Source }
}
if (!(Test-Path -LiteralPath (Join-Path $projectDir 'backend/assessment.sqlite3'))) {
    & $PythonPath (Join-Path $projectDir 'backend/build_draft_bank.py')
    if ($LASTEXITCODE -ne 0) { throw '題庫建立失敗。' }
}
$pidFile=Join-Path $runtimeDir 'server.pid'
if (Test-Path -LiteralPath $pidFile) {
    $oldId=[int](Get-Content -LiteralPath $pidFile)
    $oldProc=Get-CimInstance Win32_Process -Filter "ProcessId=$oldId" -ErrorAction SilentlyContinue
    if ($oldProc -and $oldProc.CommandLine -like '*llm-assessment*server.py*') {
        Write-Output "服務已執行：http://127.0.0.1:$Port。需變更HTTPS模式時先執行Stop-App.ps1。"
        return
    }
}
$env:ASSESSMENT_PUBLIC_HTTPS=if($PublicHttps){'1'}else{'0'}
$serverFile=Join-Path $projectDir 'backend/server.py'
$serverArgs=@('-X','utf8',('"'+$serverFile+'"'),'--port',"$Port")
$proc=Start-Process -FilePath $PythonPath -ArgumentList $serverArgs -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'server.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'server.stderr.log')
$proc.Id | Set-Content -LiteralPath $pidFile
Write-Output "Local: http://127.0.0.1:$Port"
Write-Output '首次啟動請在本機瀏覽器建立管理者。AI使用本機Ollama，Python正式執行使用WSL2 Ubuntu隔離沙箱。'

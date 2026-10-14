param([string]$NgrokPath='', [int]$Port=8765)
$ErrorActionPreference='Stop'
$projectDir=Split-Path -Parent $PSScriptRoot
$runtimeDir=Join-Path $projectDir '.runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
if(!$NgrokPath){
    $command=Get-Command ngrok -ErrorAction SilentlyContinue
    if($command){$NgrokPath=$command.Source}
    else {$NgrokPath=Join-Path $runtimeDir 'tools/ngrok.exe'}
}
if(!(Test-Path -LiteralPath $NgrokPath)){throw '找不到 ngrok。請從官方網站安裝，或用 -NgrokPath 指定執行檔。'}
$pythonPath=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if(!(Test-Path -LiteralPath $pythonPath)){$pythonPath=(Get-Command python).Source}
$adminCount=& $pythonPath -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("SELECT COUNT(*) FROM users WHERE role=\"admin\"").fetchone()[0])' (Join-Path $projectDir 'backend/assessment.sqlite3')
if($LASTEXITCODE -ne 0 -or [int]$adminCount -eq 0){throw '請先使用本機網站建立管理者帳戶，再開放對外通道。'}
# No tokens in arguments or logs; ngrok reads the user configured credential.
& (Join-Path $PSScriptRoot 'Stop-App.ps1')
& (Join-Path $PSScriptRoot 'Start-App.ps1') -Port $Port -PublicHttps -PythonPath $pythonPath
$serverReady=$false
for($checkIndex=0;$checkIndex -lt 10;$checkIndex++){
    try{ $null=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2; $serverReady=$true; break }
    catch{Start-Sleep -Milliseconds 500}
}
if(!$serverReady){throw '網站未完成啟動，未建立對外通道。請檢查 .runtime/server.stderr.log。'}
$proc=Start-Process -FilePath $NgrokPath -ArgumentList @('http',"$Port",'--log=stdout','--log-format=json') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'ngrok.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'ngrok.stderr.log')
$proc.Id | Set-Content -LiteralPath (Join-Path $runtimeDir 'ngrok.pid')
Write-Output '已啟動ngrok。請在ngrok儀表板確認免費額度；通道URL可透過本機http://127.0.0.1:4040/api/tunnels查看。'

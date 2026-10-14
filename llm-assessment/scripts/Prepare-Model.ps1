param([string]$OllamaPath='')
$ErrorActionPreference='Stop'
$projectDir=Split-Path -Parent $PSScriptRoot
$runtimeDir=Join-Path $projectDir '.runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
if(!$OllamaPath){
    $installedOllama=Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
    if(Test-Path -LiteralPath $installedOllama){$OllamaPath=$installedOllama}
    else{$OllamaPath=(Get-Command ollama -ErrorAction Stop).Source}
}
try{$models=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3}
catch{
    $null=Start-Process -FilePath $OllamaPath -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'ollama.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'ollama.stderr.log')
    $models=$null
    for($checkIndex=0;$checkIndex -lt 10;$checkIndex++){
        try{$models=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2;break}
        catch{Start-Sleep -Milliseconds 500}
    }
    if(!$models){throw 'Ollama 尚未啟動，請檢查 .runtime/ollama.stderr.log。'}
}
if(!($models.models.name -contains 'gpt-oss:20b')){
    $pullPidFile=Join-Path $runtimeDir 'gpt-oss-pull.pid'
    $pullRunning=$false
    if(Test-Path -LiteralPath $pullPidFile){
        $pullId=[int](Get-Content -LiteralPath $pullPidFile)
        $pullProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$pullId" -ErrorAction SilentlyContinue
        $pullRunning=$pullProcess -and $pullProcess.CommandLine -like '*ollama*pull*gpt-oss:20b*'
    }
    if(!$pullRunning){
        $pullProcess=Start-Process -FilePath $OllamaPath -ArgumentList @('pull','gpt-oss:20b') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'gpt-oss-pull.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'gpt-oss-pull.stderr.log')
        $pullProcess.Id | Set-Content -LiteralPath $pullPidFile
    }
    Write-Output 'gpt-oss:20b 在背景下載，可繼續測試網站。下載進度：.runtime/gpt-oss-pull.stderr.log'
}else{Write-Output 'gpt-oss:20b 已下載。'}
$verifyPidFile=Join-Path $runtimeDir 'gpt-oss-verification.pid'
$verifyRunning=$false
if(Test-Path -LiteralPath $verifyPidFile){
    $verifyId=[int](Get-Content -LiteralPath $verifyPidFile)
    $verifyProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$verifyId" -ErrorAction SilentlyContinue
    $verifyRunning=$verifyProcess -and $verifyProcess.CommandLine -like '*verify_model.py*'
}
if(!$verifyRunning){
    $pythonPath=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if(!(Test-Path -LiteralPath $pythonPath)){$pythonPath=(Get-Command python).Source}
    $verifyFile=Join-Path $PSScriptRoot 'verify_model.py'
    $verifyProcess=Start-Process -FilePath $pythonPath -ArgumentList @('-u',('"'+$verifyFile+'"'),'--wait-seconds','14400') -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'gpt-oss-verification.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'gpt-oss-verification.stderr.log')
    $verifyProcess.Id | Set-Content -LiteralPath $verifyPidFile
}
Write-Output '下載完成後會執行一次實際批改驗證；結果：.runtime/gpt-oss-verification.stdout.log，錯誤：.runtime/gpt-oss-verification.stderr.log。'

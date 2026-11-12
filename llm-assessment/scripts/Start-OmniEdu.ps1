param([Parameter(Mandatory=$true)][string]$PackagePath,[string]$PythonPath='',[int]$Port=8767)
$ErrorActionPreference='Stop'
$projectDir=Split-Path -Parent $PSScriptRoot
$runtimeDir=Join-Path $projectDir '.runtime'
if(!$PythonPath){$PythonPath=Join-Path $runtimeDir 'omni-env/Scripts/python.exe'}
if(!(Test-Path -LiteralPath $PythonPath)){throw '請先建立獨立 OmniEdu 環境，依 requirements-omni.txt 安裝套件。'}
$packageDir=(Resolve-Path -LiteralPath $PackagePath).Path
if(!(Test-Path -LiteralPath (Join-Path $packageDir 'adapter/adapter_model.safetensors'))){throw '找不到 OmniEdu adapter 權重。'}
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$pidFile=Join-Path $runtimeDir 'omni.pid'
if(Test-Path -LiteralPath $pidFile){
 $existingId=[int](Get-Content -LiteralPath $pidFile)
 $existing=Get-CimInstance Win32_Process -Filter "ProcessId=$existingId" -ErrorAction SilentlyContinue
 if($existing -and $existing.CommandLine -like '*llm-assessment*omni_server.py*'){Write-Output 'OmniEdu 本機服務已啟動。';return}
}
$serverFile=Join-Path $projectDir 'backend/omni_server.py'
$argsList=@('-X','utf8',('"'+$serverFile+'"'),'--package',('"'+$packageDir+'"'),'--port',"$Port")
$process=Start-Process -FilePath $PythonPath -ArgumentList $argsList -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'omni.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'omni.stderr.log')
$process.Id | Set-Content -LiteralPath $pidFile
Write-Output "OmniEdu: http://127.0.0.1:$Port/v1。首次作答才載入 GPU；模型及 tokenizer 僅讀取本機檔案。"

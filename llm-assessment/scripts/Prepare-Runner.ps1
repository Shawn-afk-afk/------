param([string]$Distro='Ubuntu')
$ErrorActionPreference='Stop'
wsl -d $Distro -- sh -c 'command -v python3 && command -v bwrap && command -v prlimit'
if($LASTEXITCODE -ne 0){throw '請在 WSL Ubuntu 執行 sudo apt update && sudo apt install python3 bubblewrap util-linux，再重試。'}
$env:ASSESSMENT_WSL_DISTRO=$Distro
$pythonPath=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if(!(Test-Path -LiteralPath $pythonPath)){$pythonPath=(Get-Command python).Source}
Push-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')
try {
    & $pythonPath -c 'import runner; result=runner.availability(); print(result); raise SystemExit(0 if result["available"] else 1)'
    if($LASTEXITCODE -ne 0){throw 'WSL2 網路／程序／檔案隔離驗證失敗，不會降級為直接執行。'}
} finally {Pop-Location}
Write-Output 'WSL2 正式 Python 沙箱已就緒，不需要 GPU 或 Docker。'

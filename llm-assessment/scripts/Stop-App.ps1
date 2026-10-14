$ErrorActionPreference='Stop'
$projectDir=Split-Path -Parent $PSScriptRoot
foreach($name in @('server','ngrok')) {
    $pidFile=Join-Path $projectDir ".runtime/$name.pid"
    if(Test-Path -LiteralPath $pidFile){
        $taskId=[int](Get-Content -LiteralPath $pidFile)
        $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$taskId" -ErrorAction SilentlyContinue
        if($proc -and (($name -eq 'server' -and $proc.CommandLine -like '*llm-assessment*server.py*') -or ($name -eq 'ngrok' -and $proc.CommandLine -like '*ngrok*http*8765*'))){
            Stop-Process -Id $taskId -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $pidFile -Force
    }
}
Write-Output '已停止本網站服務及由腳本啟動的通道。共用 Ollama 與 WSL2 保持運作。'

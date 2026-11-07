$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 环境创建失败，请确认已安装 Python 3.11 或更高版本。' }
}
& $projectPython -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络后重试。' }
Write-Host '环境已就绪。运行 .\start.ps1，然后打开 http://127.0.0.1:8507'

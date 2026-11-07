$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw '请先运行 setup.ps1 安装此项目的独立环境。'
}
& $projectPython -m streamlit run app.py --server.address 127.0.0.1 --server.port 8507

param(
    [int]$Port = 8787,
    [string]$Database = 'outputs/product-demo/cqa-1.2.1.sqlite3',
    [string]$Settings = 'config/settings.product.json',
    [string]$Checklist = 'config/checklist.review-v4.1.json'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$cqaPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $cqaPython)) { throw 'Create the Python environment described in README first.' }
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Port must be between 1024 and 65535.' }
$cqaSeed = @('outputs/product-demo/cqa-1.2.1.sqlite3', 'outputs/product-demo/cqa.sqlite3', 'data/workspace.sqlite3', 'data/cqa.sqlite3') |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not (Test-Path -LiteralPath $Database) -and $cqaSeed) {
    $cqaBackupScript = @'
import pathlib, sqlite3, sys
source = pathlib.Path(sys.argv[1]).resolve()
target = pathlib.Path(sys.argv[2]).resolve()
assert source != target and not target.exists()
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
    with sqlite3.connect(target) as copy:
        original.backup(copy)
'@
    $cqaBackupScript | & $cqaPython -X utf8 - $cqaSeed $Database
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare a separate product database.' }
}
Write-Host "Status CQA: http://127.0.0.1:$Port/"
$cqaArguments = @('-m', 'cqa.web', '--port', $Port, '--db', $Database, '--settings', $Settings, '--checklist', $Checklist)
if (Test-Path -LiteralPath 'data/audio' -PathType Container) { $cqaArguments += @('--audio-dir', 'data/audio') }
& $cqaPython @cqaArguments
exit $LASTEXITCODE

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "PDFjsNormalizerGUI - Windows EXE Builder"
Write-Host ""

$pythonCandidates = @(
    @{ Cmd = "py"; Args = @("-3.12") },
    @{ Cmd = "py"; Args = @("-3.13") },
    @{ Cmd = "py"; Args = @("-3") },
    @{ Cmd = "python"; Args = @() }
)

$py = $null
foreach ($candidate in $pythonCandidates) {
    try {
        & $candidate.Cmd @($candidate.Args + @("--version")) | Out-Host
        $py = $candidate
        break
    } catch {
        continue
    }
}

if ($null -eq $py) {
    throw "Python was not found. Install Python 3.12 or 3.13."
}

if (!(Test-Path ".venv\Scripts\python.exe")) {
    & $py.Cmd @($py.Args + @("-m", "venv", ".venv"))
}

& ".\.venv\Scripts\Activate.ps1"

python -m pip install --upgrade pip
python -m pip install --no-cache-dir -r requirements.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PDFjsNormalizerGUI app.py

Write-Host ""
Write-Host "Build complete:"
Write-Host "$PWD\dist\PDFjsNormalizerGUI.exe"

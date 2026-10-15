$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
}
& '.venv\Scripts\python.exe' -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
& '.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python package installation failed.' }
# Optional hardware adapters are installed on Windows. Mock mode works without devices.
& '.venv\Scripts\python.exe' -m pip install 'opencv-python>=4.10,<5' 'pywin32>=308,<400'
if ($LASTEXITCODE -ne 0) { throw 'Hardware adapter installation failed.' }
& '.venv\Scripts\python.exe' scripts\generate_frames.py
if ($LASTEXITCODE -ne 0) { throw 'Frame generation failed.' }
Push-Location frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host 'STEM 4CUT setup complete. Run scripts\run_windows.bat.'

# QAptain Backend — Restart Script
# Run this from the backend\ directory in a PowerShell terminal
# Usage: .\restart-server.ps1

Write-Host "Stopping any existing uvicorn/python processes on port 8000..." -ForegroundColor Yellow

# Kill processes holding port 8000
$port8000 = netstat -ano | Select-String ":8000 " | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Sort-Object -Unique
foreach ($pid in $port8000) {
    try {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  Killed PID $pid" -ForegroundColor Green
    } catch {}
}

Start-Sleep -Seconds 1

Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& ".\.venv\Scripts\Activate.ps1"

Write-Host "Starting QAptain backend with hot-reload..." -ForegroundColor Green
Write-Host "(Changes to .py files will be picked up automatically)" -ForegroundColor Cyan
Write-Host ""

python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

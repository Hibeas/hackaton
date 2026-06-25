# Start Port AI backend — frees port 8001 when possible, falls back to 8002.
$ErrorActionPreference = "Stop"
$BackendDir = Split-Path $PSScriptRoot -Parent
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$PreferredPort = 8001
$FallbackPort = 8002

function Test-PortListenable([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listener) {
        return $true
    }
    $pid = $listener.OwningProcess
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stopping process on port ${Port}: $($proc.ProcessName) (PID $pid)"
        Stop-Process -Id $pid -Force
        Start-Sleep -Seconds 2
        return -not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    }
    Write-Warning "Port $Port is held by dead/zombie PID $pid — cannot bind."
    return $false
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "Missing venv at $VenvPython. Run: python -m venv .venv; pip install -r requirements.txt"
}

$Port = $PreferredPort
if (-not (Test-PortListenable $PreferredPort)) {
    Write-Warning "Falling back to port $FallbackPort"
    $Port = $FallbackPort
    if (-not (Test-PortListenable $FallbackPort)) {
        Write-Error "Neither port $PreferredPort nor $FallbackPort is available."
    }
}

$FrontendEnv = Join-Path (Split-Path $BackendDir -Parent) "frontend\.env.local"
"VITE_BACKEND_URL=http://127.0.0.1:$Port" | Set-Content -Path $FrontendEnv -Encoding utf8
Write-Host "Backend URL: http://127.0.0.1:$Port"
Write-Host "Wrote $FrontendEnv — restart 'npm run dev' if frontend is already running."
Write-Host ""

Set-Location $BackendDir
& $VenvPython -m uvicorn main:app --host 127.0.0.1 --port $Port --reload

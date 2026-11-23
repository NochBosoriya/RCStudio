@echo off
chcp 65001 >nul
echo ============================================
echo RCStudio Backend + Cloudflare Tunnel Launcher
echo ============================================
echo.

:: 1. Check Docker is running
echo [1/5] Checking Docker...
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not running. Please start Docker Desktop and try again.
    exit /b 1
)
echo OK: Docker is running.
echo.

:: 2. Start backend services
echo [2/5] Starting backend services (api, worker, redis)...
docker compose up -d api worker redis
if %errorlevel% neq 0 (
    echo ERROR: Failed to start services. Check docker compose logs.
    exit /b 1
)
echo OK: Services started.
echo.

:: 3. Poll health endpoint
echo [3/5] Waiting for API health check at http://127.0.0.1:8001/health ...
set MAX_TRIES=30
set TRY=0
:health_loop
timeout /t 2 /nobreak >nul
curl -s -f http://127.0.0.1:8001/health >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo OK: API is healthy!
    goto :after_health
)
set /a TRY+=1
if %TRY% geq %MAX_TRIES% (
    echo.
    echo ERROR: API health check failed after %MAX_TRIES% attempts.
    echo Check logs with: docker compose logs api
    exit /b 1
)
echo - Waiting... (%TRY%/%MAX_TRIES%)
goto :health_loop

:after_health
echo.

:: 4. Check cloudflared
echo [4/5] Checking for cloudflared...
where cloudflared >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: cloudflared not found in PATH.
    echo Install with: winget install -e --id Cloudflare.cloudflared
    echo Or download from: https://github.com/cloudflare/cloudflared/releases
    echo.
    set /p ANSWER="Continue anyway? (y/N): "
    if /i "%ANSWER%" neq "y" (
        echo Aborted.
        exit /b 1
    )
) else (
    echo OK: cloudflared found.
)
echo.

:: 5. Launch Cloudflare Tunnel
echo [5/5] Starting Cloudflare Tunnel...
echo.
echo ============================================
echo Cloudflare Tunnel is starting...
echo Copy the https://*.trycloudflare.com URL below
echo and paste it into the Vercel frontend
echo "Backend Connection Settings" modal.
echo ============================================
echo.
cloudflared tunnel --url http://127.0.0.1:8001
@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo   KhmerDub Studio - Development Startup
echo ==========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM Check if Node.js is available
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found in PATH. Please install Node.js 18+ from nodejs.org
    pause
    exit /b 1
)

REM Check if backend/.env exists
if not exist "backend\.env" (
    echo [WARN] backend/.env not found. Copying from example...
    if exist "backend\.env.example" (
        copy "backend\.env.example" "backend\.env" >nul
        echo [INFO] Created backend/.env - please edit with your API keys (GEMINI_API_KEY, etc.)
    ) else (
        echo [ERROR] No backend/.env.example found. Create backend/.env manually.
        pause
        exit /b 1
    )
)

echo [1/6] Setting up Python virtual environment...
if not exist "venv" (
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
)

echo [2/6] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)

echo [3/6] Upgrading pip (using python -m pip to avoid Device Guard blocking pip.exe)...
python -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo [WARN] pip upgrade failed, continuing anyway...
)

echo [4/6] Installing backend dependencies...
python -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install backend dependencies
    echo [HINT] If you see "Access is denied" or "Device Guard" errors, your organization
    echo        blocks executable files in the project directory. Try running from a
    echo        different location or use Docker: docker compose up -d
    pause
    exit /b 1
)

echo [5/6] Initializing database...
cd backend
python -c "from app.db.init_db import init_db; init_db()" 2>&1
if errorlevel 1 (
    echo [WARN] Database init had issues (may be OK if tables exist)
)
cd ..

echo [6/6] Installing frontend dependencies...
cd frontend
if not exist "node_modules" (
    npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install frontend dependencies
        cd ..
        pause
        exit /b 1
    )
)
cd ..

echo.
echo ==========================================
echo   Starting services...
echo ==========================================
echo.
echo [INFO] Starting Redis and PostgreSQL via Docker...
docker compose up -d redis db
if errorlevel 1 (
    echo [WARN] Docker compose failed. Make sure Docker Desktop is running.
    echo [INFO] You can also start services manually:
    echo        redis-server
    echo        pg_ctl -D /path/to/data start
)

echo [INFO] Waiting for database to be healthy...
timeout /t 5 /nobreak >nul

echo.
echo ==========================================
echo   Starting API server (backend)...
echo ==========================================
echo.
echo [INFO] API will run at: http://localhost:8000
echo [INFO] API docs at:     http://localhost:8000/docs
echo [INFO] Press Ctrl+C in this window to stop the API server
echo.

REM Start API in background (new window)
start "KhmerDub API" cmd /k "cd /d %CD%\backend && call ..\venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --port 8000"

echo [INFO] Waiting for API to start...
timeout /t 3 /nobreak >nul

echo.
echo ==========================================
echo   Starting Celery worker (background tasks)...
echo ==========================================
echo.
start "KhmerDub Worker" cmd /k "cd /d %CD%\backend && call ..\venv\Scripts\activate.bat && celery -A app.tasks worker --loglevel=info"

echo.
echo ==========================================
echo   Starting Frontend (Next.js)...
echo ==========================================
echo.
echo [INFO] Frontend will run at: http://localhost:3000
echo [INFO] Press Ctrl+C in the frontend window to stop
echo.

start "KhmerDub Frontend" cmd /k "cd /d %CD%\frontend && npm run dev"

echo.
echo ==========================================
echo   All services started!
echo ==========================================
echo.
echo API:        http://localhost:8000
echo API Docs:   http://localhost:8000/docs
echo Frontend:   http://localhost:3000
echo Redis:      localhost:6379
echo PostgreSQL: localhost:5432
echo.
echo To stop all services, close the three command windows that opened,
echo or run: docker compose down
echo.
pause
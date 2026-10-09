<# 
.SYNOPSIS
    OtelMS API - Local Development Runner (Windows PowerShell)
    
.DESCRIPTION
    Starts all services locally for development:
    - PostgreSQL (via Docker)
    - Redis (via Docker)
    - FastAPI API server
    - Celery Worker
    - Celery Beat (scheduler)
    
    Browser runs in HEADFUL mode (visible) for local debugging.
    In Docker, it runs headless via SCRAPER_HEADLESS=true.
#>

param(
    [switch]$NoDocker = $false
)

$ErrorActionPreference = "Stop"

# Colors
$Red = [ConsoleColor]::Red
$Green = [ConsoleColor]::Green
$Yellow = [ConsoleColor]::Yellow
$Blue = [ConsoleColor]::Cyan
$Default = [ConsoleColor]::Gray

function Write-Color($Message, $Color = $Default) {
    Write-Host $Message -ForegroundColor $Color
}

function Write-Section($Title) {
    Write-Color "========================================" $Blue
    Write-Color "  $Title" $Blue
    Write-Color "========================================" $Blue
    Write-Host ""
}

Write-Section "OtelMS API - Local Development Runner (Windows)"

# Check prerequisites
Write-Color "Checking prerequisites..." $Yellow

$missing = @()
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $missing += "python" }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { $missing += "uv (install with: pip install uv)" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { $missing += "docker" }

if ($missing.Count -gt 0) {
    Write-Color "Missing prerequisites:" $Red
    $missing | ForEach-Object { Write-Color "  - $_" $Red }
    exit 1
}

# Check Docker is running
try {
    docker info > $null 2>&1
} catch {
    Write-Color "Error: Docker is not running. Please start Docker first." $Red
    exit 1
}

Write-Color "Prerequisites OK" $Green
Write-Host ""

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

# Start PostgreSQL and Redis via Docker Compose
if (-not $NoDocker) {
    Write-Color "Starting PostgreSQL and Redis..." $Yellow
    docker compose -f docker/docker-compose.yml up -d postgres redis

    # Wait for services to be healthy
    Write-Color "Waiting for services to be healthy..." $Yellow
    Start-Sleep -Seconds 5

    # Check PostgreSQL
    for ($i = 1; $i -le 30; $i++) {
        try {
            $result = docker compose -f docker/docker-compose.yml exec -T postgres pg_isready -U otelms -d otelms 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Color "PostgreSQL is ready" $Green
                break
            }
        } catch {}
        if ($i -eq 30) { Write-Color "PostgreSQL failed to start" $Red; exit 1 }
        Start-Sleep -Seconds 1
    }

    # Check Redis
    for ($i = 1; $i -le 30; $i++) {
        try {
            $result = docker compose -f docker/docker-compose.yml exec -T redis redis-cli ping 2>$null
            if ($LASTEXITCODE -eq 0 -and $result -like "*PONG*") {
                Write-Color "Redis is ready" $Green
                break
            }
        } catch {}
        if ($i -eq 30) { Write-Color "Redis failed to start" $Red; exit 1 }
        Start-Sleep -Seconds 1
    }
    Write-Host ""
}

# Run database migrations
Write-Color "Running database migrations..." $Yellow
uv run alembic upgrade head
Write-Color "Migrations complete" $Green
Write-Host ""

# Create .env.local for local development
$envLocalContent = @"
# Local development overrides
# This file is loaded AFTER .env, so it takes precedence

# API - disable key requirement for local testing
API_KEY_REQUIRED=false

# Browser - VISIBLE (headless=false) for local debugging
SCRAPER_HEADLESS=false
BROWSER_HEADLESS=false

# Logging - console format for local dev
LOG_FORMAT=console
LOG_LEVEL=DEBUG

# Disable proxy for local testing (unless needed)
USE_PROXY=false

# Database - use PostgreSQL from Docker (port 5433)
DATABASE_URL=postgresql+asyncpg://otelms:otelms_dev_password@localhost:5433/otelms

# Redis - use Redis from Docker (port 6380)
REDIS_URL=redis://localhost:6380/0
CELERY_BROKER_URL=redis://localhost:6380/1
CELERY_RESULT_BACKEND=redis://localhost:6380/2
"@

$envLocalPath = Join-Path $projectRoot ".env.local"
$envLocalContent | Out-File -FilePath $envLocalPath -Encoding utf8
Write-Color "Created .env.local with local overrides" $Green
Write-Host ""

# Load environment files
function Load-EnvFile($path) {
    if (Test-Path $path) {
        Get-Content $path | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#")) {
                $parts = $line -split "=", 2
                if ($parts.Count -eq 2) {
                    $name = $parts[0].Trim()
                    $value = $parts[1].Trim()
                    # Remove surrounding quotes if present
                    if ($value.StartsWith('"') -and $value.EndsWith('"')) {
                        $value = $value.Substring(1, $value.Length - 2)
                    }
                    [Environment]::SetEnvironmentVariable($name, $value, "Process")
                }
            }
        }
    }
}

Load-EnvFile ".env"
Load-EnvFile ".env.local"

# Create logs directory
$logsDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }

# Track background jobs
$jobs = @()

function Start-Service($Name, $Command, $Arguments) {
    Write-Color "Starting $Name..." $Blue
    $stdoutLog = Join-Path $logsDir "$Name.stdout.log"
    $stderrLog = Join-Path $logsDir "$Name.stderr.log"
    $pidFile = Join-Path $logsDir "$Name.pid"
    
    $process = Start-Process -FilePath $Command -ArgumentList $Arguments -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru -WindowStyle Hidden
    $process.Id | Out-File -FilePath $pidFile
    $jobs += @{ Name = $Name; Process = $process; StdoutLog = $stdoutLog; StderrLog = $stderrLog; PidFile = $pidFile }
    
    Write-Color "$Name started (PID: $($process.Id), stdout: $stdoutLog, stderr: $stderrLog)" $Green
}

# Start services (use port 8001 to avoid conflicts with other services on 8000)
Start-Service "api" "uv" @("run", "uvicorn", "otelms.api.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload", "--log-level", "debug")
Start-Service "worker" "uv" @("run", "celery", "-A", "otelms.tasks.celery_app", "worker", "--loglevel=info", "--concurrency=2", "-Q", "celery,scraping")
Start-Service "beat" "uv" @("run", "celery", "-A", "otelms.tasks.celery_app", "beat", "--loglevel=info", "--scheduler", "redbeat.RedBeatScheduler")

Write-Host ""
Write-Section "All services started!"
Write-Host ""
Write-Color "API Server:      http://localhost:8001" $Blue
Write-Color "Swagger UI:      http://localhost:8001/docs" $Blue
Write-Color "ReDoc:           http://localhost:8001/redoc" $Blue
Write-Color "OpenAPI JSON:    http://localhost:8001/openapi.json" $Blue
Write-Color "Prometheus:      http://localhost:9090/metrics" $Blue
Write-Host ""
Write-Color "PostgreSQL:      localhost:5433 (user: otelms, pass: otelms_dev_password, db: otelms)" $Blue
Write-Color "Redis:           localhost:6380" $Blue
Write-Host ""
Write-Color "Logs:            .\logs\" $Blue
Write-Color "PIDs:            .\logs\*.pid" $Blue
Write-Host ""
Write-Color "Press Ctrl+C to stop all services" $Yellow
Write-Host ""

# Cleanup function
function Stop-Services {
    Write-Host ""
    Write-Color "Stopping services..." $Yellow
    
    foreach ($job in $jobs) {
        $pid = Get-Content $job.PidFile -ErrorAction SilentlyContinue
        if ($pid) {
            try {
                $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($proc -and -not $proc.HasExited) {
                    Write-Color "Stopping $($job.Name) (PID: $pid)..." $Blue
                    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }
    }
    
    if (-not $NoDocker) {
        Write-Color "Stopping PostgreSQL and Redis..." $Blue
        docker compose -f docker/docker-compose.yml down
    }
    
    Write-Color "All services stopped" $Green
}

# Register cleanup on exit
$global:cleanupRegistered = $true
Register-EngineEvent -SourceIdentifier "PowerShell.Exiting" -Action { Stop-Services } | Out-Null

# Also handle Ctrl+C
try {
    while ($true) {
        Start-Sleep -Seconds 1
        # Check if any process died
        foreach ($job in $jobs) {
            $proc = Get-Process -Id $job.Process.Id -ErrorAction SilentlyContinue
            if (-not $proc -or $proc.HasExited) {
                Write-Color "$($job.Name) process exited unexpectedly. Check log: $($job.LogFile)" $Red
            }
        }
    }
} catch {
    Stop-Services
    exit 1
}
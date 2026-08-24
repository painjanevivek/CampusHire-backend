param(
    [int]$ApiPort = 8010,
    [int]$PostgresPort = 55433,
    [int]$RedisPort = 6389,
    [int]$ClamAvPort = 53310,
    [int]$Samples = 20,
    [int]$Rounds = 3,
    [int]$Concurrency = 4,
    [int]$ResumeSamples = 5,
    [string]$OutputPath = ".data/performance-rehearsal-phase7e.json"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot

$runId = "phase7e-$PID"
$postgresName = "campushire-perf-postgres-$PID"
$redisName = "campushire-perf-redis-$PID"
$clamAvName = "campushire-perf-clamav-$PID"
$postgresPassword = [Guid]::NewGuid().ToString("N")
$redisPassword = [Guid]::NewGuid().ToString("N")
$studentPassword = [Guid]::NewGuid().ToString("N")
$adminPassword = [Guid]::NewGuid().ToString("N")
$runtimeDirectory = Join-Path $repositoryRoot ".data\$runId"
$baselinePath = Join-Path $repositoryRoot ".data\pilot-http-baseline-phase7e.json"
$costPath = Join-Path $repositoryRoot ".data\pilot-cost-proposal-phase7e.json"
$apiProcess = $null
$workerProcess = $null
$startedContainers = [System.Collections.Generic.List[string]]::new()

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

try {
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

    & docker run --rm --detach --name $postgresName `
        --publish "${PostgresPort}:5432" `
        --env "POSTGRES_PASSWORD=$postgresPassword" `
        --env "POSTGRES_DB=campushire" `
        postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73 *> $null
    Assert-LastExitCode -Step "PostgreSQL startup"
    $startedContainers.Add($postgresName)

    & docker run --rm --detach --name $redisName `
        --publish "${RedisPort}:6379" `
        redis:8-alpine@sha256:becdda6c7f4b3fb42e42fd7f120bbf5c54c4caaaf16f26da24e4563d2c1f0576 `
        redis-server --appendonly no --requirepass $redisPassword *> $null
    Assert-LastExitCode -Step "Redis startup"
    $startedContainers.Add($redisName)

    & docker run --rm --detach --name $clamAvName `
        --publish "${ClamAvPort}:3310" `
        clamav/clamav:stable@sha256:0e85467cb0d6e7d860a45035707741cd5ffc032ffefc6002a3510c75b6d07027 *> $null
    Assert-LastExitCode -Step "ClamAV startup"
    $startedContainers.Add($clamAvName)

    $dependenciesReady = $false
    for ($attempt = 1; $attempt -le 60; $attempt += 1) {
        & docker exec $postgresName pg_isready -U postgres -d campushire *> $null
        $postgresReady = $LASTEXITCODE -eq 0
        & docker exec $redisName redis-cli -a $redisPassword ping *> $null
        $redisReady = $LASTEXITCODE -eq 0
        $clamAvHealth = & docker inspect --format "{{.State.Health.Status}}" $clamAvName 2>$null
        if ($postgresReady -and $redisReady -and $clamAvHealth -eq "healthy") {
            $dependenciesReady = $true
            break
        }
        if ($attempt % 10 -eq 0) {
            Write-Output "Waiting for dependencies: attempt=$attempt clamav=$clamAvHealth"
        }
        Start-Sleep -Seconds 2
    }
    if (-not $dependenciesReady) {
        throw "Performance dependencies did not become healthy within 120 seconds."
    }

    $env:APP_ENV = "development"
    $env:DATABASE_URL = "postgresql+asyncpg://postgres:$postgresPassword@127.0.0.1:$PostgresPort/campushire"
    $env:REDIS_URL = "redis://:$redisPassword@127.0.0.1:$RedisPort/0"
    $env:FRONTEND_ORIGINS = '["http://127.0.0.1:3000"]'
    $env:TRUSTED_HOSTS = '["127.0.0.1","localhost"]'
    $env:MALWARE_SCANNER = "clamav"
    $env:CLAMAV_HOST = "127.0.0.1"
    $env:CLAMAV_PORT = "$ClamAvPort"
    $env:RESUME_PARSER_BACKEND = "docker"
    $env:RESUME_PARSER_IMAGE = "campushire-pdf-parser:test"
    $env:RESUME_WORKER_POLL_SECONDS = "0.2"
    $env:RESUME_STORAGE_PATH = ".data/$runId/resumes"
    $env:GEMINI_API_KEY = ""
    $env:QDRANT_URL = "http://127.0.0.1:1"
    $env:SEMANTIC_MATCH_REQUESTS_PER_MINUTE = "100"
    $env:PERFORMANCE_FIXTURE_ACK = "synthetic-only"
    $env:PERFORMANCE_STUDENT_PASSWORD = $studentPassword
    $env:PERFORMANCE_ADMIN_PASSWORD = $adminPassword

    & ".\.venv\Scripts\python.exe" -m alembic upgrade head
    Assert-LastExitCode -Step "Migration"
    $fixture = & ".\.venv\Scripts\python.exe" scripts\seed_performance_fixture.py |
        ConvertFrom-Json
    Assert-LastExitCode -Step "Synthetic performance seed"
    if ($fixture.data_class -ne "synthetic-only") {
        throw "The performance fixture did not confirm its synthetic data class."
    }

    $apiProcess = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -WorkingDirectory $repositoryRoot `
        -RedirectStandardOutput (Join-Path $runtimeDirectory "api.stdout.log") `
        -RedirectStandardError (Join-Path $runtimeDirectory "api.stderr.log") `
        -WindowStyle Hidden `
        -PassThru
    $workerProcess = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList @("-m", "app.worker") `
        -WorkingDirectory $repositoryRoot `
        -RedirectStandardOutput (Join-Path $runtimeDirectory "worker.stdout.log") `
        -RedirectStandardError (Join-Path $runtimeDirectory "worker.stderr.log") `
        -WindowStyle Hidden `
        -PassThru

    $apiReady = $false
    for ($attempt = 1; $attempt -le 60; $attempt += 1) {
        try {
            $health = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$ApiPort/api/v1/health/ready" `
                -Headers @{Origin = "http://127.0.0.1:3000"} `
                -TimeoutSec 2
            if ($health.StatusCode -eq 200) {
                $apiReady = $true
                break
            }
        }
        catch {
            # Continue until the bounded startup deadline.
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $apiReady) {
        throw "The performance API did not become ready within 30 seconds."
    }

    $env:PILOT_STUDENT_EMAIL = $fixture.student_email
    $env:PILOT_STUDENT_PASSWORD = $studentPassword
    $env:PILOT_ADMIN_EMAIL = $fixture.admin_email
    $env:PILOT_ADMIN_PASSWORD = $adminPassword
    $env:PILOT_ROLE_ID = $fixture.role_id
    $env:PILOT_RESUME_VERSION_ID = $fixture.resume_version_id
    & ".\.venv\Scripts\python.exe" scripts\measure_pilot_http.py `
        --base-url "http://127.0.0.1:$ApiPort/api/v1" `
        --origin "http://127.0.0.1:3000" `
        --samples $Samples `
        --rounds $Rounds `
        --concurrency $Concurrency `
        --expect-ai-degraded `
        --resume-processing-samples $ResumeSamples `
        --environment-label "local-production-shaped-dependencies-not-capacity" `
        --output $baselinePath
    Assert-LastExitCode -Step "HTTP and worker baseline"

    & ".\.venv\Scripts\python.exe" scripts\estimate_pilot_cost.py --output $costPath
    Assert-LastExitCode -Step "Pilot cost proposal"

    $apiStats = Get-Process -Id $apiProcess.Id |
        Select-Object Id, CPU, WorkingSet64, PrivateMemorySize64
    $workerStats = Get-Process -Id $workerProcess.Id |
        Select-Object Id, CPU, WorkingSet64, PrivateMemorySize64
    $containerStats = @(
        & docker stats --no-stream --format "{{json .}}" `
            $postgresName $redisName $clamAvName |
            ForEach-Object { $_ | ConvertFrom-Json }
    )
    Assert-LastExitCode -Step "Container resource snapshot"
    $databaseStats = & docker exec $postgresName psql -U postgres -d campushire -tAc (
        "SELECT json_build_object(" +
        "'active_connections', (SELECT count(*) FROM pg_stat_activity " +
        "WHERE datname='campushire' AND state='active'), " +
        "'total_connections', (SELECT count(*) FROM pg_stat_activity " +
        "WHERE datname='campushire'), " +
        "'commits', (SELECT xact_commit FROM pg_stat_database WHERE datname='campushire'), " +
        "'rollbacks', (SELECT xact_rollback FROM pg_stat_database WHERE datname='campushire'))"
    ) | ConvertFrom-Json
    Assert-LastExitCode -Step "Database resource snapshot"

    $result = [ordered]@{
        recorded_at_utc = [DateTime]::UtcNow.ToString("o")
        environment = "local-production-shaped-dependencies-not-capacity"
        data_class = "synthetic-only"
        backend_commit = (& git rev-parse HEAD)
        workload = (Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json)
        cost_proposal = (Get-Content -LiteralPath $costPath -Raw | ConvertFrom-Json)
        point_in_time_resources = [ordered]@{
            api = $apiStats
            worker = $workerStats
            containers = $containerStats
            database = $databaseStats
        }
        passed = $true
    }
    $resolvedOutput = Join-Path $repositoryRoot $OutputPath
    New-Item -ItemType Directory -Path (Split-Path -Parent $resolvedOutput) -Force | Out-Null
    $result | ConvertTo-Json -Depth 10 | Set-Content -Path $resolvedOutput -Encoding utf8
    $result | ConvertTo-Json -Depth 10
}
finally {
    if ($null -ne $workerProcess -and -not $workerProcess.HasExited) {
        Stop-Process -Id $workerProcess.Id -Force
    }
    if ($null -ne $apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -Force
    }
    foreach ($container in $startedContainers) {
        $existing = & docker ps -a --filter "name=^/$container$" --format "{{.Names}}"
        if ($existing -eq $container) {
            & docker stop $container *> $null
        }
    }
}

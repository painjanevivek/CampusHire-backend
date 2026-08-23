param(
    [int]$HostPort = 55432,
    [string]$OutputPath = ".data/release-rehearsal.json"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot

$containerName = "campushire-recovery-$PID"
$databaseName = "campushire"
$restoreDatabaseName = "campushire_restore"
$databasePassword = [Guid]::NewGuid().ToString("N")
$databaseUrl = "postgresql+asyncpg://postgres:$databasePassword@127.0.0.1:$HostPort/$databaseName"
$previousDatabaseUrl = $env:DATABASE_URL
$containerStarted = $false

function Invoke-TimedStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    & $Action
    $exitCode = $LASTEXITCODE
    $stopwatch.Stop()
    if ($null -ne $exitCode -and $exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode."
    }
    return [math]::Round($stopwatch.Elapsed.TotalMilliseconds)
}

function Invoke-PostgresScalar {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Query
    )

    $value = & docker exec $containerName psql -U postgres -d $Database -tAc $Query
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL verification query failed."
    }
    return ($value | Out-String).Trim()
}

try {
    $existingContainer = & docker ps -a --filter "name=^/$containerName$" --format "{{.ID}}"
    if ($existingContainer) {
        throw "Refusing to reuse an existing container named $containerName."
    }

    $containerId = & docker run --rm --detach `
        --name $containerName `
        --publish "${HostPort}:5432" `
        --env "POSTGRES_PASSWORD=$databasePassword" `
        --env "POSTGRES_DB=$databaseName" `
        postgres:16-alpine
    if ($LASTEXITCODE -ne 0 -or -not $containerId) {
        throw "Unable to start the isolated PostgreSQL rehearsal container."
    }
    $containerStarted = $true

    $ready = $false
    for ($attempt = 1; $attempt -le 45; $attempt += 1) {
        & docker exec $containerName pg_isready -U postgres -d $databaseName *> $null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "PostgreSQL did not become ready within 45 seconds."
    }

    $env:DATABASE_URL = $databaseUrl
    $upgradeMs = Invoke-TimedStep -Name "Initial migration" -Action {
        & ".\.venv\Scripts\python.exe" -m alembic upgrade head
    }
    $headBeforeRollback = Invoke-PostgresScalar -Database $databaseName -Query (
        "SELECT version_num FROM alembic_version"
    )

    $downgradeMs = Invoke-TimedStep -Name "One-revision rollback" -Action {
        & ".\.venv\Scripts\python.exe" -m alembic downgrade -1
    }
    $rollbackHead = Invoke-PostgresScalar -Database $databaseName -Query (
        "SELECT version_num FROM alembic_version"
    )

    $rollForwardMs = Invoke-TimedStep -Name "Roll forward after rollback" -Action {
        & ".\.venv\Scripts\python.exe" -m alembic upgrade head
    }
    $headAfterRollForward = Invoke-PostgresScalar -Database $databaseName -Query (
        "SELECT version_num FROM alembic_version"
    )

    & docker exec $containerName psql -U postgres -d $databaseName -v ON_ERROR_STOP=1 -c (
        "CREATE TABLE recovery_probe (marker text PRIMARY KEY); " +
        "INSERT INTO recovery_probe(marker) VALUES ('campushire-phase6');"
    ) *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the recovery probe."
    }

    $backupMs = Invoke-TimedStep -Name "Logical backup" -Action {
        & docker exec $containerName pg_dump -U postgres -d $databaseName `
            --format=custom --file=/tmp/campushire.dump
    }
    & docker exec $containerName createdb -U postgres $restoreDatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the isolated restore database."
    }
    $restoreMs = Invoke-TimedStep -Name "Logical restore" -Action {
        & docker exec $containerName pg_restore -U postgres -d $restoreDatabaseName `
            --no-owner --no-privileges /tmp/campushire.dump
    }

    $restoredHead = Invoke-PostgresScalar -Database $restoreDatabaseName -Query (
        "SELECT version_num FROM alembic_version"
    )
    $restoredProbe = Invoke-PostgresScalar -Database $restoreDatabaseName -Query (
        "SELECT marker FROM recovery_probe"
    )
    $restoredTableCount = [int](Invoke-PostgresScalar -Database $restoreDatabaseName -Query (
        "SELECT count(*) FROM information_schema.tables " +
        "WHERE table_schema = 'public'"
    ))

    if ($headBeforeRollback -ne $headAfterRollForward -or $headBeforeRollback -ne $restoredHead) {
        throw "Migration head changed across rollback, roll-forward, or restore."
    }
    if ($restoredProbe -ne "campushire-phase6") {
        throw "The restored recovery probe does not match the source database."
    }

    $result = [ordered]@{
        recorded_at_utc = [DateTime]::UtcNow.ToString("o")
        topology = "isolated-postgres-16-container"
        source_database = $databaseName
        restore_database = $restoreDatabaseName
        migration_head = $headBeforeRollback
        rollback_head = $rollbackHead
        restored_table_count = $restoredTableCount
        recovery_probe = $restoredProbe
        timings_ms = [ordered]@{
            initial_upgrade = $upgradeMs
            downgrade_one_revision = $downgradeMs
            roll_forward = $rollForwardMs
            logical_backup = $backupMs
            logical_restore = $restoreMs
        }
        assertions = [ordered]@{
            rollback_changed_head = ($rollbackHead -ne $headBeforeRollback)
            roll_forward_restored_head = ($headAfterRollForward -eq $headBeforeRollback)
            backup_restore_preserved_head = ($restoredHead -eq $headBeforeRollback)
            backup_restore_preserved_probe = ($restoredProbe -eq "campushire-phase6")
        }
    }

    $resolvedOutput = Join-Path $repositoryRoot $OutputPath
    New-Item -ItemType Directory -Path (Split-Path -Parent $resolvedOutput) -Force | Out-Null
    $result | ConvertTo-Json -Depth 6 | Set-Content -Path $resolvedOutput -Encoding utf8
    $result | ConvertTo-Json -Depth 6
}
finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:DATABASE_URL = $previousDatabaseUrl
    }
    if ($containerStarted) {
        & docker stop $containerName *> $null
    }
}

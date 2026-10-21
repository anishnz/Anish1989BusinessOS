# Starts Anish1989 Business OS with Docker on Windows.
#
# Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
#
# What it does:
#   1. Checks that Docker Desktop is running.
#   2. Creates a .env file with random local passwords if it does not exist yet.
#   3. Pulls the pre-built images (same versions on every laptop) or builds them if needed.
#   4. Starts everything and waits until the platform is healthy.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function New-RandomHex([int]$bytes) {
    $buffer = New-Object byte[] $bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($buffer)
    $rng.Dispose()
    return -join ($buffer | ForEach-Object { $_.ToString("x2") })
}

Write-Host "== Anish1989 Business OS ==" -ForegroundColor Cyan

# 1. Docker running?
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running. Start Docker Desktop, wait until it says 'Engine running', then run this script again." -ForegroundColor Red
    exit 1
}

# 2. Create .env once, with random local secrets.
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env with random local passwords..."
    $secret = New-RandomHex 40
    $dbPassword = New-RandomHex 16
    $content = (Get-Content ".env.example" -Raw)
    $content = $content -replace "(?m)^DJANGO_SECRET_KEY=.*$", "DJANGO_SECRET_KEY=$secret"
    $content = $content -replace "(?m)^POSTGRES_PASSWORD=.*$", "POSTGRES_PASSWORD=$dbPassword"
    $content = $content -replace "(?m)^DATABASE_URL=.*$", "DATABASE_URL=postgres://businessos:$dbPassword@db:5432/businessos"
    $content = $content -replace "`r`n", "`n"
    # UTF-8 without BOM, Linux line endings (Docker reads this file).
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $content, (New-Object System.Text.UTF8Encoding $false))
} else {
    Write-Host ".env already exists, keeping it."
}

# 2b. Make sure there is a vault master key (also for older .env files).
$envText = Get-Content ".env" -Raw
if ($envText -notmatch "(?m)^VAULT_MASTER_KEYS=\S+") {
    Write-Host "Creating the secret vault master key..."
    $keyBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($keyBytes)
    $rng.Dispose()
    $vaultKey = "k1:" + [Convert]::ToBase64String($keyBytes)
    if ($envText -match "(?m)^VAULT_MASTER_KEYS=") {
        $envText = $envText -replace "(?m)^VAULT_MASTER_KEYS=.*$", "VAULT_MASTER_KEYS=$vaultKey"
    } else {
        $envText = $envText.TrimEnd() + "`nVAULT_MASTER_KEYS=$vaultKey`n"
    }
    $envText = $envText -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $envText, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "IMPORTANT: back up the VAULT_MASTER_KEYS line from .env (for example in a password manager)." -ForegroundColor Yellow
}

# 2c. Make sure there is a backup encryption key (task 1.14; also for older .env files).
$envText = Get-Content ".env" -Raw
if ($envText -notmatch "(?m)^BACKUP_ENCRYPTION_KEYS=\S+") {
    Write-Host "Creating the backup encryption key..."
    $keyBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($keyBytes)
    $rng.Dispose()
    $backupKey = "b1:" + [Convert]::ToBase64String($keyBytes)
    if ($envText -match "(?m)^BACKUP_ENCRYPTION_KEYS=") {
        $envText = $envText -replace "(?m)^BACKUP_ENCRYPTION_KEYS=.*$", "BACKUP_ENCRYPTION_KEYS=$backupKey"
    } else {
        $envText = $envText.TrimEnd() + "`nBACKUP_ENCRYPTION_KEYS=$backupKey`n"
    }
    $envText = $envText -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $envText, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "IMPORTANT: back up the BACKUP_ENCRYPTION_KEYS line from .env too. Without it, backups cannot be opened." -ForegroundColor Yellow
}

# 3. Get images: pull pre-built ones, build only what could not be pulled.
Write-Host "Pulling images (first time can take a few minutes)..."
docker compose pull --ignore-pull-failures
Write-Host "Starting services..."
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker could not start the services. See the messages above." -ForegroundColor Red
    exit 1
}

# 4. Wait until healthy.
Write-Host "Waiting for the platform to become healthy..."
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health/" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 3
}

if ($healthy) {
    Write-Host ""
    Write-Host "Platform is running." -ForegroundColor Green
    Write-Host "  Health:          http://localhost:8000/health/"
    Write-Host "  Platform admin:  http://localhost:8000/admin/"
    Write-Host ""
    Write-Host "Next steps (you type the password yourself):"
    Write-Host "  Create the Super Admin:"
    Write-Host "    docker compose exec web python manage.py createsuperuser"
    Write-Host "  Create a test business:"
    Write-Host "    docker compose exec web python manage.py create_business --name ""Gorkha Butchery"" --slug gorkhabutchery --industry butchery"
    Write-Host "    then open http://gorkhabutchery.localhost:8000/admin/"
    Write-Host ""
    Write-Host "Stop:  docker compose down      (your data is kept)"
} else {
    Write-Host "The platform did not become healthy in time. Recent logs:" -ForegroundColor Yellow
    docker compose ps
    docker compose logs --tail 40 web
    exit 1
}

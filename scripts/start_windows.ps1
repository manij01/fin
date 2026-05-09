$ErrorActionPreference = "Stop"

$ContainerName = "finally"
$ImageName = "finally"
$Port = 8000
$EnvFile = ".env"

Set-Location "$PSScriptRoot\.."

$DockerEnvArgs = @()
if (Test-Path $EnvFile) {
    $DockerEnvArgs = @("--env-file", $EnvFile)
} else {
    Write-Host "No .env found; starting with simulator defaults. Copy .env.example to .env to configure API keys."
}

# Build if image doesn't exist or -Build flag passed
$needsBuild = $args -contains "--build"
if (-not $needsBuild) {
    docker image inspect $ImageName 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $needsBuild = $true }
}

if ($needsBuild) {
    Write-Host "Building image..."
    docker build -t $ImageName .
}

# Stop existing container if present (idempotent)
$ExistingContainer = docker ps -aq --filter "name=^/$ContainerName$"
if ($ExistingContainer) {
    docker rm -f $ContainerName | Out-Null
}

# Run container
docker run -d `
    --name $ContainerName `
    -p "${Port}:8000" `
    -v finally-data:/app/db `
    -e DB_PATH=/app/db/finally.db `
    @DockerEnvArgs `
    $ImageName

Write-Host "FinAlly running at http://localhost:$Port"
Start-Process "http://localhost:$Port"

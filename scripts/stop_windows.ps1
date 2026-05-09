$ErrorActionPreference = "Stop"

$ContainerName = "finally"

# Stop and remove container if present, keep volume (idempotent)
$ExistingContainer = docker ps -aq --filter "name=^/$ContainerName$"
if ($ExistingContainer) {
    docker rm -f $ContainerName | Out-Null
}

Write-Host "FinAlly stopped."

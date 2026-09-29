$ErrorActionPreference = "Stop"
$container = "n8n-n8n-1"
$workflow = Join-Path $PSScriptRoot "sentinel-scheduled-checks.json"

if (-not (Test-Path $workflow)) {
    throw "Missing workflow file: $workflow"
}

docker compose -f (Join-Path $PSScriptRoot "docker-compose.yml") up -d | Out-Host

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $health = Invoke-WebRequest -Uri "http://127.0.0.1:5678/healthz" -UseBasicParsing -TimeoutSec 3
        if ($health.StatusCode -ge 200) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    throw "n8n did not become ready on http://127.0.0.1:5678"
}

docker cp $workflow "${container}:/home/node/sentinel-scheduled-checks.json" | Out-Host
docker exec $container n8n import:workflow --input=/home/node/sentinel-scheduled-checks.json --overwrite | Out-Host

$listed = docker exec $container n8n list:workflow
Write-Host $listed

$ids = @()
foreach ($line in ($listed -split "`n")) {
    if ($line -match "^([^|]+)\|") {
        $ids += $Matches[1].Trim()
    }
}

if ($ids.Count -eq 0) {
    $ids += "sentinel-scheduled-checks"
}

foreach ($id in $ids) {
    docker exec $container n8n publish:workflow --id=$id
    docker exec $container n8n update:workflow --id=$id --active=true 2>$null
}

Write-Host "Imported Sentinel scheduled checks (every 10 seconds)."
Write-Host "Active workflows:"
docker exec $container n8n list:workflow --active=true
Write-Host "Open http://localhost:5678 and confirm the workflow is Active."

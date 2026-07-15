param(
    [ValidateSet("build", "push", "all")]
    [string]$Action = "all",

    [string]$DockerUser = "upsgabriel",
    [string]$Tag = "1.0.0"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$images = @(
    @{
        Name = "$DockerUser/ticket-api-gateway:$Tag"
        Context = ".\api-gateway"
    },
    @{
        Name = "$DockerUser/ticket-reservation-service:$Tag"
        Context = ".\reservation-service"
    },
    @{
        Name = "$DockerUser/ticket-inventory-service:$Tag"
        Context = ".\inventory-service"
    }
)

if ($Action -in @("build", "all")) {
    Write-Host "=== Construyendo imágenes GABO ==="

    foreach ($image in $images) {
        Write-Host "Construyendo $($image.Name)..."
        docker build -t $image.Name $image.Context

        if ($LASTEXITCODE -ne 0) {
            throw "Falló la construcción de $($image.Name)"
        }
    }
}

if ($Action -in @("push", "all")) {
    Write-Host "=== Publicando imágenes en Docker Hub ==="
    Write-Host "Asegúrate de haber ejecutado docker login."

    foreach ($image in $images) {
        Write-Host "Publicando $($image.Name)..."
        docker push $image.Name

        if ($LASTEXITCODE -ne 0) {
            throw "Falló la publicación de $($image.Name)"
        }
    }
}

Write-Host "=== Imágenes GABO listas ==="
$images | ForEach-Object { Write-Host $_.Name }

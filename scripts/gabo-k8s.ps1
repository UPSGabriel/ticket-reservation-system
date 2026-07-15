param(
    [ValidateSet("deploy", "status", "forward", "logs", "delete")]
    [string]$Action = "deploy"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$namespace = "ticket-system"

function Confirm-Kubectl {
    kubectl cluster-info | Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "kubectl no está conectado a un clúster Kubernetes."
    }
}

Confirm-Kubectl

switch ($Action) {
    "deploy" {
        Write-Host "=== Desplegando Parte GABO en Kubernetes ==="
        kubectl apply -f .\k8s\gabo\all.yaml

        if ($LASTEXITCODE -ne 0) {
            throw "No fue posible aplicar los manifiestos."
        }

        Write-Host "Esperando PostgreSQL..."
        kubectl rollout status deployment/postgres -n $namespace --timeout=240s

        Write-Host "Esperando Inventory Service..."
        kubectl rollout status deployment/inventory-service -n $namespace --timeout=240s

        Write-Host "Esperando Reservation Service..."
        kubectl rollout status deployment/reservation-service -n $namespace --timeout=240s

        Write-Host "Esperando API Gateway..."
        kubectl rollout status deployment/api-gateway -n $namespace --timeout=240s

        Write-Host "=== Despliegue terminado ==="
        kubectl get nodes -o wide
        kubectl get pods -n $namespace -o wide
        kubectl get services -n $namespace
    }

    "status" {
        Write-Host "=== Nodos ==="
        kubectl get nodes -o wide

        Write-Host "=== Pods GABO ==="
        kubectl get pods -n $namespace -o wide

        Write-Host "=== Servicios GABO ==="
        kubectl get services -n $namespace

        Write-Host "=== Réplicas ==="
        kubectl get deployments -n $namespace
    }

    "forward" {
        $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue

        if ($listener) {
            throw "El puerto 8000 ya está ocupado. Ejecuta docker compose down o cierra el proceso anterior."
        }

        Write-Host "Gateway disponible en http://localhost:8000/docs"
        Write-Host "Mantén esta terminal abierta. Usa Ctrl+C para detener el port-forward."
        kubectl port-forward service/api-gateway 8000:8000 -n $namespace
    }

    "logs" {
        Write-Host "=== Logs API Gateway ==="
        kubectl logs deployment/api-gateway -n $namespace --tail=60

        Write-Host "=== Logs Reservation Service ==="
        kubectl logs deployment/reservation-service -n $namespace --tail=60

        Write-Host "=== Logs Inventory Service ==="
        kubectl logs deployment/inventory-service -n $namespace --tail=60
    }

    "delete" {
        Write-Host "Eliminando namespace $namespace..."
        kubectl delete namespace $namespace --ignore-not-found=true
    }
}

param(
    [ValidateSet("deploy", "status", "dns", "logs", "delete")]
    [string]$Action = "deploy"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$namespace = "ticket-system"

function Confirm-CommandSucceeded {
    param([string]$Message)

    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

function Confirm-Kubectl {
    kubectl cluster-info | Out-Null
    Confirm-CommandSucceeded "kubectl no esta conectado a un cluster."

    kubectl get namespace $namespace | Out-Null
    Confirm-CommandSucceeded `
        "El namespace $namespace no existe. Despliega primero k8s/gabo/all.yaml."
}

function Show-ApplicationLogs {
    param([string]$Application)

    $pods = kubectl get pods `
        -n $namespace `
        -l "app=$Application" `
        -o jsonpath="{.items[*].metadata.name}"
    Confirm-CommandSucceeded "No se pudieron consultar pods de $Application."

    foreach ($pod in ($pods -split " ")) {
        if ([string]::IsNullOrWhiteSpace($pod)) {
            continue
        }

        Write-Host "--- $Application / $pod ---"
        kubectl logs $pod -n $namespace --tail=100
        Confirm-CommandSucceeded "No se pudieron leer logs de $pod."
    }
}

Confirm-Kubectl

switch ($Action) {
    "deploy" {
        Write-Host "=== Desplegando servicios JORDY ==="
        kubectl apply -f .\k8s\jordy\all.yaml
        Confirm-CommandSucceeded "No fue posible aplicar k8s/jordy/all.yaml."

        kubectl rollout status `
            deployment/payment-service `
            -n $namespace `
            --timeout=240s
        Confirm-CommandSucceeded "Payment Service no termino su rollout."

        kubectl rollout status `
            deployment/notification-service `
            -n $namespace `
            --timeout=240s
        Confirm-CommandSucceeded "Notification Service no termino su rollout."

        kubectl get pods -n $namespace -o wide
        kubectl get services -n $namespace
    }

    "status" {
        Write-Host "=== Nodos ==="
        kubectl get nodes -o wide

        Write-Host "=== Servicios JORDY ==="
        kubectl get deployments,pods,services `
            -n $namespace `
            -l "app in (payment-service,notification-service)" `
            -o wide
    }

    "dns" {
        Write-Host "=== DNS interno desde Reservation Service ==="
        $pythonCode = @"
import urllib.request
for url in (
    'http://payment-service:8003/health',
    'http://notification-service:8004/health',
):
    print(url, urllib.request.urlopen(url, timeout=5).read().decode())
"@
        kubectl exec `
            -n $namespace `
            deployment/reservation-service `
            -- python -c $pythonCode
        Confirm-CommandSucceeded "Fallo la resolucion DNS interna."
    }

    "logs" {
        Show-ApplicationLogs -Application "payment-service"
        Show-ApplicationLogs -Application "notification-service"
    }

    "delete" {
        Write-Host "Eliminando solo los recursos de Jordy..."
        kubectl delete `
            -f .\k8s\jordy\all.yaml `
            --ignore-not-found=true
        Confirm-CommandSucceeded "No se pudieron eliminar los recursos de Jordy."
    }
}

param(
    [string]$Namespace = "ticket-system",
    [string]$WorkerNode = "ticket-cluster-worker"
)

$ErrorActionPreference = "Stop"

Write-Host "=== INVENTARIO FANTASMA ==="

$podInventario = kubectl get pods `
    -n $Namespace `
    -l app=inventory-service `
    --field-selector spec.nodeName=$WorkerNode `
    -o jsonpath="{.items[0].metadata.name}"

if ([string]::IsNullOrWhiteSpace($podInventario)) {
    throw "No se encontró una réplica de Inventario en $WorkerNode."
}

Write-Host "Pod que será eliminado:" $podInventario
kubectl delete pod $podInventario -n $Namespace

Write-Host "Estado inmediato:"
kubectl get pods -n $Namespace -l app=inventory-service -o wide

Write-Host "Esperando recuperación automática..."
kubectl wait `
    --for=condition=Ready `
    pod `
    -l app=inventory-service `
    -n $Namespace `
    --timeout=120s

Write-Host "Estado recuperado:"
kubectl get pods -n $Namespace -l app=inventory-service -o wide

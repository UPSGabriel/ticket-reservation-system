param(
    [string]$Namespace = "ticket-system",
    [int]$LocalPort = 8005,
    [int]$Requests = 15
)

$ErrorActionPreference = "Stop"

Write-Host "=== DILUVIO DE PETICIONES ==="

$gatewayPod = kubectl get pods `
    -n $Namespace `
    -l app=api-gateway `
    -o jsonpath="{.items[0].metadata.name}"

if ([string]::IsNullOrWhiteSpace($gatewayPod)) {
    throw "No se encontró un pod del API Gateway."
}

Write-Host "Gateway seleccionado:" $gatewayPod

$forwardJob = Start-Job -ScriptBlock {
    param($Pod, $Port, $Ns)
    kubectl port-forward "pod/$Pod" "${Port}:8000" -n $Ns
} -ArgumentList $gatewayPod, $LocalPort, $Namespace

try {
    Start-Sleep -Seconds 4

    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()

    try {
        1..$Requests | ForEach-Object {
            $response = $client.GetAsync("http://localhost:$LocalPort/rate-test").Result
            Write-Host "Solicitud $_ -> HTTP $([int]$response.StatusCode)"
        }
    }
    finally {
        $client.Dispose()
    }

    Write-Host "`n=== LOGS DE RATE LIMITING ==="
    kubectl logs $gatewayPod -n $Namespace --tail=60 |
        Select-String "rate limiting"

    Write-Host "`nEsperando recuperación de la ventana..."
    Start-Sleep -Seconds 11
    curl.exe -i "http://localhost:$LocalPort/rate-test"
}
finally {
    Stop-Job $forwardJob -ErrorAction SilentlyContinue
    Remove-Job $forwardJob -Force -ErrorAction SilentlyContinue
}

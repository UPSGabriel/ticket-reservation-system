param(
    [string]$GatewayUrl = "http://localhost:8000",
    [string]$Namespace = "ticket-system"
)

$ErrorActionPreference = "Stop"

function Send-Reservation {
    param(
        [int]$UserId,
        [int]$EventId = 1,
        [int]$Quantity = 1
    )

    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue

    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds(30)

    $body = @{
        event_id = $EventId
        user_id = $UserId
        quantity = $Quantity
    } | ConvertTo-Json -Compress

    $content = [System.Net.Http.StringContent]::new(
        $body,
        [System.Text.Encoding]::UTF8,
        "application/json"
    )

    try {
        $response = $client.PostAsync(
            "$GatewayUrl/api/reservations",
            $content
        ).Result

        return [PSCustomObject]@{
            StatusCode = [int]$response.StatusCode
            Body = $response.Content.ReadAsStringAsync().Result
        }
    }
    finally {
        $client.Dispose()
    }
}

function Wait-PostgresStopped {
    param([string]$Namespace)

    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $replicas = kubectl get deployment/postgres `
            -n $Namespace `
            -o jsonpath="{.status.replicas}"

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo consultar el estado de PostgreSQL."
        }

        if (
            [string]::IsNullOrWhiteSpace($replicas) -or
            [int]$replicas -eq 0
        ) {
            Write-Host "PostgreSQL apagado correctamente."
            return
        }

        Start-Sleep -Seconds 2
    }

    throw "PostgreSQL no termino de apagarse dentro del tiempo esperado."
}

Write-Host "=== BASE DE DATOS INTERMITENTE ==="
Write-Host "Este escenario apaga PostgreSQL temporalmente y comprueba la recuperacion."
Write-Host "Manten activo el port-forward del Gateway en $GatewayUrl"

kubectl get deployment postgres -n $Namespace | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "No se encontro PostgreSQL en el namespace $Namespace."
}

Start-Sleep -Seconds 11

try {
    Write-Host "`n1. Estado inicial de PostgreSQL"
    kubectl get pods -n $Namespace -l app=postgres -o wide

    Write-Host "`n2. Apagando PostgreSQL..."
    kubectl scale deployment/postgres --replicas=0 -n $Namespace
    Wait-PostgresStopped -Namespace $Namespace

    Write-Host "`n3. Intentando reservar mientras la base esta caida..."
    $duringFailure = Send-Reservation -UserId 401
    Write-Host "HTTP durante el fallo:" $duringFailure.StatusCode
    Write-Host $duringFailure.Body

    if ($duringFailure.StatusCode -lt 500) {
        Write-Warning "Se esperaba un error controlado 5xx mientras PostgreSQL estaba apagado."
    }
}
finally {
    Write-Host "`n4. Restaurando PostgreSQL..."
    kubectl scale deployment/postgres --replicas=1 -n $Namespace
    kubectl rollout status deployment/postgres -n $Namespace --timeout=180s
    kubectl wait --for=condition=ready pod -l app=postgres -n $Namespace --timeout=180s

    Write-Host "Esperando que Inventario y Reservas vuelvan a estar listos..."
    kubectl wait --for=condition=ready pod -l app=inventory-service -n $Namespace --timeout=180s
    kubectl wait --for=condition=ready pod -l app=reservation-service -n $Namespace --timeout=180s
}

Write-Host "`n5. Probando una reserva despues de la recuperacion..."
Start-Sleep -Seconds 5
$afterRecovery = Send-Reservation -UserId 402
Write-Host "HTTP despues de recuperar:" $afterRecovery.StatusCode
Write-Host $afterRecovery.Body

Write-Host "`n6. Verificando persistencia en PostgreSQL..."
kubectl exec -n $Namespace deployment/postgres -- psql `
    -U ticket_user `
    -d ticket_db `
    -c "SELECT event_id, available FROM inventory ORDER BY event_id; SELECT user_id, event_id, quantity, status FROM reservations WHERE user_id IN (401, 402) ORDER BY created_at;"

Write-Host "`n=== RESULTADO ESPERADO ==="
Write-Host "Durante el fallo: HTTP 503 o 504 controlado."
Write-Host "Despues de recuperar: HTTP 200 y reserva guardada para el usuario 402."
Write-Host "Los datos anteriores deben conservarse gracias al volumen persistente."

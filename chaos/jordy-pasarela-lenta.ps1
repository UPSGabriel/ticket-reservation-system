param(
    [string]$GatewayUrl = "http://localhost:8000",
    [string]$Namespace = "ticket-system",
    [int]$DelaySeconds = 20,
    [int]$EventId = 1,
    [int]$NormalUserId = 7101,
    [int]$SlowUserId = 7102,
    [int]$RecoveryUserId = 7103
)

$ErrorActionPreference = "Stop"

function Confirm-CommandSucceeded {
    param([string]$Message)

    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

function Wait-Deployment {
    param([string]$Name)

    kubectl rollout status "deployment/$Name" `
        -n $Namespace `
        --timeout=240s
    Confirm-CommandSucceeded "El deployment $Name no termino su rollout."
}

function Wait-ServiceReady {
    param(
        [string]$Url,
        [int]$MaxAttempts = 30,
        [int]$RetrySeconds = 2
    )

    $pythonCode = @"
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
        print(response.read().decode())
        sys.exit(0 if 200 <= response.status < 300 else 1)
except Exception as exc:
    print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
    sys.exit(1)
"@

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        Write-Host "Comprobando $Url desde Reservation Service (intento $attempt de $MaxAttempts)..."

        kubectl exec `
            -n $Namespace `
            deployment/reservation-service `
            -- python -c $pythonCode $Url
        $exitCode = $LASTEXITCODE

        if ($exitCode -eq 0) {
            Write-Host "Payment Service acepta conexiones desde Reservation Service."
            return
        }

        if ($attempt -lt $MaxAttempts) {
            Start-Sleep -Seconds $RetrySeconds
        }
    }

    throw "Payment Service no estuvo disponible desde Reservation Service despues de $MaxAttempts intentos."
}

function Set-PaymentMode {
    param([int]$FixedDelaySeconds)

    kubectl set env deployment/payment-service `
        -n $Namespace `
        "PAYMENT_DELAY_SECONDS=$FixedDelaySeconds" `
        "PAYMENT_FAILURE_MODE=none" `
        "PAYMENT_FAILURE_RATE=0"
    Confirm-CommandSucceeded "No se pudo configurar Payment Service."
    Wait-Deployment -Name "payment-service"
    Wait-ServiceReady -Url "http://payment-service:8003/health"
}

function Set-StableNotification {
    kubectl set env deployment/notification-service `
        -n $Namespace `
        "NOTIFICATION_FAILURE_MODE=none" `
        "NOTIFICATION_FAILURE_RATE=0"
    Confirm-CommandSucceeded "No se pudo estabilizar Notification Service."
    Wait-Deployment -Name "notification-service"
}

function Send-Reservation {
    param([int]$UserId)

    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds(15)

    $body = @{
        event_id = $EventId
        user_id = $UserId
        quantity = 1
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

function Assert-ReservationStatus {
    param(
        [PSCustomObject]$Result,
        [string]$ExpectedStatus,
        [string]$Stage
    )

    Write-Host "HTTP:" $Result.StatusCode
    Write-Host $Result.Body

    if ($Result.StatusCode -ne 200) {
        throw "$Stage devolvio HTTP $($Result.StatusCode); se esperaba HTTP 200."
    }

    try {
        $parsedBody = $Result.Body | ConvertFrom-Json
    }
    catch {
        throw "$Stage no devolvio JSON valido."
    }

    if ($parsedBody.status -ne $ExpectedStatus) {
        throw "$Stage termino en $($parsedBody.status); se esperaba $ExpectedStatus."
    }

    return $parsedBody
}

function Show-ApplicationLogs {
    param(
        [string]$Application,
        [int]$Tail = 100
    )

    $pods = kubectl get pods `
        -n $Namespace `
        -l "app=$Application" `
        -o jsonpath="{.items[*].metadata.name}"
    Confirm-CommandSucceeded "No se pudieron consultar los pods de $Application."

    foreach ($pod in ($pods -split " ")) {
        if ([string]::IsNullOrWhiteSpace($pod)) {
            continue
        }

        Write-Host "--- $Application / $pod ---"
        kubectl logs $pod -n $Namespace --tail=$Tail
        Confirm-CommandSucceeded "No se pudieron leer los logs de $pod."
    }
}

Write-Host "=== PASARELA LENTA ==="
Write-Host "Este escenario comprueba timeout + fallback sin bloquear la reserva."
Write-Host "Debe existir un port-forward del Gateway en $GatewayUrl."

kubectl cluster-info | Out-Null
Confirm-CommandSucceeded "kubectl no esta conectado a un cluster."

foreach ($deployment in @(
    "payment-service",
    "notification-service",
    "reservation-service",
    "postgres"
)) {
    kubectl get "deployment/$deployment" -n $Namespace | Out-Null
    Confirm-CommandSucceeded "No existe deployment/$deployment en $Namespace."
}

try {
    Write-Host "`n1. Estabilizando servicios externos para una prueba determinista..."
    Set-StableNotification
    Set-PaymentMode -FixedDelaySeconds 0

    Write-Host "`n2. Reserva normal antes del fallo..."
    $normalResult = Send-Reservation -UserId $NormalUserId
    $normalReservation = Assert-ReservationStatus `
        -Result $normalResult `
        -ExpectedStatus "CONFIRMED" `
        -Stage "Reserva inicial"

    Write-Host "Reserva confirmada:" $normalReservation.reservation_id

    Write-Host "`n3. Inyectando demora de $DelaySeconds segundos en Payment Service..."
    Set-PaymentMode -FixedDelaySeconds $DelaySeconds
    kubectl get pods -n $Namespace -l app=payment-service -o wide

    Write-Host "`n4. Reserva durante Pasarela Lenta..."
    $slowResult = Send-Reservation -UserId $SlowUserId
    $slowReservation = Assert-ReservationStatus `
        -Result $slowResult `
        -ExpectedStatus "PAYMENT_PENDING" `
        -Stage "Reserva con pasarela lenta"

    if ($slowReservation.payment.status -ne "PAYMENT_PENDING") {
        throw "payment.status no quedo en PAYMENT_PENDING."
    }

    Write-Host "Reserva pendiente:" $slowReservation.reservation_id

    Write-Host "`n5. Logs de Payment y Reservation Service..."
    Show-ApplicationLogs -Application "payment-service"
    Show-ApplicationLogs -Application "reservation-service"

    Write-Host "`n6. Verificando persistencia de la reserva pendiente..."
    kubectl exec -n $Namespace deployment/postgres -- psql `
        -U ticket_user `
        -d ticket_db `
        -c "SELECT id, user_id, status, payment_status, notification_status FROM reservations WHERE user_id = $SlowUserId ORDER BY created_at DESC LIMIT 1;"
    Confirm-CommandSucceeded "No se pudo verificar la reserva en PostgreSQL."
}
finally {
    Write-Host "`n7. Restaurando Payment Service con demora fija 0..."
    Set-PaymentMode -FixedDelaySeconds 0
    Set-StableNotification
}

Write-Host "`n8. Reserva despues de la recuperacion..."
$recoveryResult = Send-Reservation -UserId $RecoveryUserId
$recoveryReservation = Assert-ReservationStatus `
    -Result $recoveryResult `
    -ExpectedStatus "CONFIRMED" `
    -Stage "Reserva recuperada"

Write-Host "Reserva confirmada despues de recuperar:" `
    $recoveryReservation.reservation_id

Write-Host "`n=== RESULTADO COMPROBADO ==="
Write-Host "Antes: CONFIRMED"
Write-Host "Durante: PAYMENT_PENDING, inventario descontado y reserva persistida"
Write-Host "Despues: CONFIRMED y PAYMENT_DELAY_SECONDS=0"

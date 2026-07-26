param(
    [ValidateSet("build", "test", "push", "all")]
    [string]$Action = "all",

    [string]$DockerUser = "upsgabriel",
    [string]$Tag = "1.0.0"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$paymentImage = "$DockerUser/ticket-payment-service:$Tag"
$notificationImage = "$DockerUser/ticket-notification-service:$Tag"

function Confirm-Docker {
    docker info | Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop no esta abierto o el motor Linux no responde."
    }
}

function Confirm-PortAvailable {
    param([int]$Port)

    $listener = Get-NetTCPConnection `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue

    if ($listener) {
        throw "El puerto $Port ya esta ocupado."
    }
}

function Wait-Health {
    param(
        [string]$Url,
        [string]$Service
    )

    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $health = Invoke-RestMethod `
                -Method Get `
                -Uri $Url `
                -TimeoutSec 2

            Write-Host "$Service health:" `
                ($health | ConvertTo-Json -Compress)
            return
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }

    throw "$Service no respondio en $Url."
}

Confirm-Docker

if ($Action -in @("build", "all")) {
    Write-Host "=== Construyendo imagenes JORDY ==="

    docker build -t $paymentImage .\payment-service
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la construccion de $paymentImage."
    }

    docker build -t $notificationImage .\notification-service
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la construccion de $notificationImage."
    }
}

if ($Action -in @("test", "all")) {
    Write-Host "=== Probando imagenes JORDY ==="
    docker rm -f ticket-payment-test ticket-notification-test 2>$null | Out-Null
    Confirm-PortAvailable -Port 8003
    Confirm-PortAvailable -Port 8004

    try {
        docker run -d `
            --name ticket-payment-test `
            -p 8003:8003 `
            -e INSTANCE_NAME=payment-docker `
            -e PAYMENT_DELAY_SECONDS=0 `
            -e PAYMENT_MIN_DELAY_MS=0 `
            -e PAYMENT_MAX_DELAY_MS=0 `
            -e PAYMENT_FAILURE_RATE=0 `
            -e PAYMENT_FAILURE_MODE=none `
            $paymentImage | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo iniciar Payment Service."
        }

        docker run -d `
            --name ticket-notification-test `
            -p 8004:8004 `
            -e INSTANCE_NAME=notification-docker `
            -e NOTIFICATION_DELAY_SECONDS=0 `
            -e NOTIFICATION_MIN_DELAY_MS=0 `
            -e NOTIFICATION_MAX_DELAY_MS=0 `
            -e NOTIFICATION_FAILURE_RATE=0 `
            -e NOTIFICATION_FAILURE_MODE=none `
            $notificationImage | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo iniciar Notification Service."
        }

        Wait-Health `
            -Url "http://localhost:8003/health" `
            -Service "Payment"
        Wait-Health `
            -Url "http://localhost:8004/health" `
            -Service "Notification"

        $reservationId = [guid]::NewGuid().ToString()

        $payment = Invoke-RestMethod `
            -Method Post `
            -Uri "http://localhost:8003/payments/process" `
            -ContentType "application/json" `
            -Body (@{
                reservation_id = $reservationId
                user_id = 101
                amount = 20.0
            } | ConvertTo-Json -Compress)

        if ($payment.status -ne "APPROVED") {
            throw "Payment no devolvio APPROVED."
        }
        Write-Host "Payment POST:" ($payment | ConvertTo-Json -Compress)

        $notification = Invoke-RestMethod `
            -Method Post `
            -Uri "http://localhost:8004/notifications/send" `
            -ContentType "application/json" `
            -Body (@{
                reservation_id = $reservationId
                user_id = 101
                message = "Su reserva fue confirmada."
            } | ConvertTo-Json -Compress)

        if ($notification.status -ne "SENT") {
            throw "Notification no devolvio SENT."
        }
        Write-Host "Notification POST:" `
            ($notification | ConvertTo-Json -Compress)
    }
    finally {
        docker rm -f ticket-payment-test ticket-notification-test 2>$null | Out-Null
    }
}

if ($Action -in @("push", "all")) {
    Write-Host "=== Publicando imagenes JORDY ==="
    Write-Host "La sesion de Docker debe pertenecer a $DockerUser."

    docker push $paymentImage
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la publicacion de $paymentImage."
    }

    docker push $notificationImage
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la publicacion de $notificationImage."
    }
}

Write-Host "=== Imagenes JORDY listas ==="
Write-Host $paymentImage
Write-Host $notificationImage

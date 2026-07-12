$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Stop-LocalPythonOnPort {
    param([int]$Port)

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue

    foreach ($listener in $listeners) {
        $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue

        if ($null -ne $process -and $process.ProcessName -match "python|uvicorn") {
            Write-Host "Deteniendo proceso local $($process.ProcessName) en puerto $Port..."
            Stop-Process -Id $listener.OwningProcess -Force
        }
    }
}

function Wait-Health {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Attempts = 30
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3
            Write-Host "$Name listo:" ($response | ConvertTo-Json -Compress)
            return
        }
        catch {
            Write-Host "Esperando $Name ($attempt/$Attempts)..."
            Start-Sleep -Seconds 2
        }
    }

    throw "$Name no respondió en $Url"
}

Write-Host "=== DEMOSTRACION DE GABRIEL ==="
Write-Host "Componentes: API Gateway, Reservation Service, Inventory Service y PostgreSQL"

Stop-LocalPythonOnPort -Port 8000
Stop-LocalPythonOnPort -Port 8001
Stop-LocalPythonOnPort -Port 8002

Write-Host "Construyendo y levantando contenedores..."
docker compose up -d --build

Wait-Health -Name "Inventory Service" -Url "http://localhost:8002/health"
Wait-Health -Name "Reservation Service" -Url "http://localhost:8001/health"
Wait-Health -Name "API Gateway" -Url "http://localhost:8000/health"

Write-Host "Reiniciando inventario de demostracion..."
$reset = Invoke-RestMethod `
    -Uri "http://localhost:8002/inventory/reset" `
    -Method Post
$reset | ConvertTo-Json -Depth 10

Write-Host "Creando reserva a traves del API Gateway..."
$body = @{
    event_id = 1
    user_id = 101
    quantity = 2
} | ConvertTo-Json

$reservation = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/reservations" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body

$reservation | ConvertTo-Json -Depth 10

Write-Host "Consultando inventario persistido..."
$inventory = Invoke-RestMethod `
    -Uri "http://localhost:8002/inventory/1" `
    -Method Get
$inventory | ConvertTo-Json -Depth 10

Write-Host "Consultando la reserva persistida..."
$reservationId = $reservation.reservation_id
$savedReservation = Invoke-RestMethod `
    -Uri "http://localhost:8001/reservations/$reservationId" `
    -Method Get
$savedReservation | ConvertTo-Json -Depth 10

Write-Host "Verificando PostgreSQL directamente..."
docker exec ticket-postgres psql `
    -U ticket_user `
    -d ticket_db `
    -c "SELECT id, event_id, user_id, quantity, status, created_at FROM reservations ORDER BY created_at DESC LIMIT 5;"

Write-Host "=== PRUEBA COMPLETADA ==="
Write-Host "Swagger Gateway:      http://localhost:8000/docs"
Write-Host "Swagger Reservas:     http://localhost:8001/docs"
Write-Host "Swagger Inventario:   http://localhost:8002/docs"
Write-Host "Estado esperado mientras Jordy completa Pagos: PAYMENT_PENDING"

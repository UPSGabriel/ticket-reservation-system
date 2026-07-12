# Ticket Reservation System

Sistema distribuido de reservas de entradas con tolerancia a fallos, persistencia en PostgreSQL, contenedores Docker y preparación para Kubernetes.

## Integrantes

- Gabriel Córdova
- Jordy Espinoza

## Parte GABO

- API Gateway con rate limiting y bulkhead.
- Reservation Service con retry, backoff, fallback y persistencia.
- Inventory Service con operaciones atómicas sobre PostgreSQL.
- PostgreSQL con eventos, inventario y reservas.
- Docker Compose para levantar toda la ruta principal.

Payment Service, Notification Service, Kubernetes y los escenarios de caos finales corresponden a la siguiente etapa del equipo.

## Arquitectura

```text
Cliente
  -> API Gateway :8000
  -> Reservation Service :8001
  -> Inventory Service :8002
  -> PostgreSQL :5432
```

## Inicio rápido

Requisitos:

- Docker Desktop abierto.
- PowerShell.

Desde la raíz del proyecto:

```powershell
git pull origin main
docker compose up -d --build
docker compose ps
```

Endpoints:

- Gateway: `http://localhost:8000/docs`
- Reservas: `http://localhost:8001/docs`
- Inventario: `http://localhost:8002/docs`

## Demo GABO

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabriel-demo.ps1
```

El script levanta los servicios, verifica los endpoints de salud, crea una reserva, comprueba el descuento de inventario y consulta la reserva persistida en PostgreSQL.

## Prueba rápida manual

```powershell
$body = @{
  event_id = 1
  user_id = 101
  quantity = 2
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://localhost:8000/api/reservations" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

Mientras Payment Service no esté implementado, el estado esperado es `PAYMENT_PENDING`; el inventario se descuenta y la reserva se guarda correctamente.

## Parte GABO

```text
docs/GABO.md
```

## Detener el sistema

```powershell
docker compose down
```

Para borrar también los datos persistidos:

```powershell
docker compose down -v
```

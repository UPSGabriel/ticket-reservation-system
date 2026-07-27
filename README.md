# Ticket Reservation System

Sistema distribuido de reservas de entradas con tolerancia a fallos, persistencia en PostgreSQL, contenedores Docker y despliegue Kubernetes multinodo.

## Integrantes

- Gabriel Córdova
- Jordy Espinoza

## Estado del proyecto

El código y los manifiestos de los seis componentes están implementados. La ejecución final en Kubernetes y la captura de evidencias deben realizarse cuando las imágenes de Payment y Notification están publicadas.

Componentes:

- API Gateway (`8000`).
- Reservation Service (`8001`).
- Inventory Service (`8002`).
- Payment Service (`8003`).
- Notification Service (`8004`).
- PostgreSQL (`5432`).

Los cuatro escenarios prácticos seleccionados son Inventario Fantasma, Pasarela Lenta, Diluvio de Peticiones y Condición de Carrera. Base de Datos Intermitente y Correo Perdido se reservan para el análisis teórico, aunque la base de datos también cuenta con una prueba adicional.

## Arquitectura

```text
Cliente
  |
  v
API Gateway
  |
  v
Reservation Service
  |------------------|-------------------|
  v                  v                   v
Inventory Service    Payment Service     Notification Service
  |
  v
PostgreSQL <---------- Reservation Service
```

La arquitectura lógica, los DNS internos y la distribución esperada entre nodos están documentados en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Requisitos

- Docker Desktop con motor Linux.
- PowerShell.
- `kubectl`.
- `kind`.
- Cuenta autorizada para publicar en `upsgabriel`.

## Descargar la rama de Jordy

```powershell
git fetch origin
git checkout jordy-servicios
git pull origin jordy-servicios
```

## Pruebas automáticas

Desde la raíz:

```powershell
Push-Location .\payment-service
python -m unittest discover -s tests -v
Pop-Location

Push-Location .\notification-service
python -m unittest discover -s tests -v
Pop-Location
```

## Imágenes Docker

Imágenes del sistema:

```text
upsgabriel/ticket-api-gateway:1.0.0
upsgabriel/ticket-reservation-service:1.0.0
upsgabriel/ticket-inventory-service:1.0.0
upsgabriel/ticket-payment-service:1.0.0
upsgabriel/ticket-notification-service:1.0.0
postgres:16-alpine
```

Construir, probar y publicar las imágenes de Gabriel:

```powershell
docker login
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-images.ps1 -Action all
```

Construir, probar y publicar Payment y Notification:

```powershell
docker login
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-images.ps1 -Action all
```

Para construir o probar sin publicar:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-images.ps1 -Action build
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-images.ps1 -Action test
```

## Clúster Kubernetes de dos nodos

Crear el clúster cuando todavía no exista:

```powershell
kind create cluster --name ticket-cluster --config .\kind-config.yaml
kubectl config use-context kind-ticket-cluster
kubectl get nodes -o wide
```

Deben aparecer un nodo `control-plane` y un nodo `worker` en estado `Ready`.

Desplegar primero la parte base y después los servicios externos:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action deploy
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action deploy
```

Verificar recursos, distribución y DNS internos:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action status
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action status
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action dns
```

Los DNS requeridos son:

```text
http://payment-service:8003
http://notification-service:8004
```

## Abrir el Gateway

Liberar el puerto local y mantener el port-forward en una terminal separada:

```powershell
docker compose down
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action forward
```

Swagger queda disponible en `http://localhost:8000/docs`.

## Reserva normal determinista

Antes de la prueba normal se desactivan únicamente los fallos aleatorios:

```powershell
kubectl set env deployment/payment-service -n ticket-system PAYMENT_DELAY_SECONDS=0 PAYMENT_FAILURE_MODE=none PAYMENT_FAILURE_RATE=0
kubectl set env deployment/notification-service -n ticket-system NOTIFICATION_DELAY_SECONDS=0 NOTIFICATION_FAILURE_MODE=none NOTIFICATION_FAILURE_RATE=0
kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

Crear una reserva:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/api/reservations `
  -ContentType application/json `
  -Body '{"event_id":1,"user_id":101,"quantity":1}' |
  ConvertTo-Json -Depth 10
```

Resultado esperado:

```text
HTTP                    200
status                  CONFIRMED
payment.status          CONFIRMED
notification.status     SENT
```

## Escenarios prácticos

Mantener activo el port-forward del Gateway.

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-inventario-fantasma.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\jordy-pasarela-lenta.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-diluvio-peticiones.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-condicion-carrera.ps1
```

Prueba adicional:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-base-datos-intermitente.ps1
```

Pasarela Lenta restaura `PAYMENT_DELAY_SECONDS=0` en un bloque `finally`, incluso si la comprobación falla.

## Evidencias y demo

- Catálogo y defensas: [docs/FALLOS.md](docs/FALLOS.md).
- Arquitectura multinodo: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).
- Guion de 10–15 minutos: [docs/DEMO.md](docs/DEMO.md).
- Evidencias requeridas: [docs/EVIDENCIAS.md](docs/EVIDENCIAS.md).
- Análisis de los dos fallos restantes: [docs/ANALISIS-FALLOS.md](docs/ANALISIS-FALLOS.md).
- Trabajo de Gabriel: [docs/GABO.md](docs/GABO.md).
- Trabajo de Jordy: [docs/JORDY.md](docs/JORDY.md).

No es obligatorio instalar un dashboard. La rúbrica acepta evidencia mediante logs, métricas o capturas; este proyecto utiliza salidas de `kubectl`, logs de pods, respuestas HTTP y consultas PostgreSQL.

## Limpieza

Eliminar solamente Payment y Notification:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action delete
```

Eliminar todo el namespace usando el flujo de Gabriel:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action delete
```

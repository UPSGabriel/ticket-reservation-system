# Ticket Reservation System

Sistema distribuido de reservas de entradas con tolerancia a fallos, persistencia en PostgreSQL, contenedores Docker y despliegue Kubernetes multinodo.

## Integrantes

- Gabriel Córdova
- Jordy Espinoza

## Estado actual

### Parte GABO — completada

- API Gateway con rate limiting, bulkhead, timeout y manejo de indisponibilidad.
- Reservation Service con retry, backoff, fallback y persistencia.
- Inventory Service con descuento atómico y prevención de sobreventa.
- PostgreSQL con eventos, inventario y reservas.
- Docker Compose para pruebas locales.
- Imágenes publicadas en Docker Hub.
- Clúster Kubernetes con dos nodos mediante `kind`.
- Dos réplicas de Gateway, Reservas e Inventario distribuidas entre ambos nodos.
- PersistentVolumeClaim para PostgreSQL.
- Health checks y PodDisruptionBudgets.

Escenarios comprobados:

1. Inventario Fantasma.
2. Condición de Carrera.
3. Diluvio de Peticiones.
4. Base de Datos Intermitente como prueba adicional de infraestructura.

### Parte JORDY — pendiente

- Payment Service.
- Notification Service.
- Imágenes Docker de ambos servicios.
- Manifiestos Kubernetes de ambos servicios.
- Integración completa con Reservation Service.
- Cuarto fallo práctico oficial: Pasarela Lenta.
- Evidencias y commits reales de Jordy.

La guía completa para continuar está en:

```text
docs/JORDY.md
```

## Arquitectura actual

```text
Cliente / Swagger
       |
       v
API Gateway :8000
       |
       v
Reservation Service :8001
       |
       v
Inventory Service :8002
       |
       v
PostgreSQL :5432
```

Cuando Jordy complete su parte, Reservation Service también se comunicará con:

```text
Payment Service      :8003
Notification Service :8004
```

## Requisitos

- Docker Desktop.
- PowerShell.
- `kubectl`.
- `kind`.
- Cuenta de Docker Hub.

## Retomar el proyecto

Desde la raíz del repositorio:

```powershell
git pull origin main
```

Comprobar el clúster:

```powershell
kind get clusters
kubectl config use-context kind-ticket-cluster
kubectl get nodes -o wide
```

Deben aparecer:

```text
ticket-cluster-control-plane   Ready
ticket-cluster-worker          Ready
```

## Construir las imágenes GABO

```powershell
docker login
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-images.ps1 -Action all
```

Imágenes publicadas:

```text
upsgabriel/ticket-api-gateway:1.0.0
upsgabriel/ticket-reservation-service:1.0.0
upsgabriel/ticket-inventory-service:1.0.0
```

## Desplegar la parte GABO en Kubernetes

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action deploy
```

Consultar el estado:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action status
```

## Abrir Swagger desde Kubernetes

Primero liberar el puerto 8000:

```powershell
docker compose down
```

Después:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action forward
```

Abrir:

```text
http://localhost:8000/docs
```

Reserva de prueba:

```json
{
  "event_id": 1,
  "user_id": 101,
  "quantity": 2
}
```

Mientras Payment Service no esté desplegado, el resultado esperado es `PAYMENT_PENDING`. El inventario sí se descuenta y la reserva sí se guarda en PostgreSQL.

## Escenarios de caos GABO

Mantener activo el port-forward del Gateway antes de los scripts que realizan solicitudes.

### Inventario Fantasma

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-inventario-fantasma.ps1
```

### Condición de Carrera

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-condicion-carrera.ps1
```

### Diluvio de Peticiones

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-diluvio-peticiones.ps1
```

### Base de Datos Intermitente — prueba adicional

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-base-datos-intermitente.ps1
```

## Resultados ya comprobados

```text
Inventario Fantasma:
- Se elimina una réplica de Inventario.
- La réplica del segundo nodo continúa atendiendo.
- Kubernetes crea automáticamente un pod nuevo.

Condición de Carrera:
- Dos usuarios compiten por el último asiento.
- Uno recibe HTTP 200.
- El otro recibe HTTP 409.
- El inventario queda en 0 y nunca es negativo.

Diluvio de Peticiones:
- Solicitudes 1 a 10 pasan por el middleware.
- Solicitudes 11 a 15 reciben HTTP 429.
- Después de 10 segundos el Gateway vuelve a aceptar solicitudes.

Base de Datos Intermitente:
- PostgreSQL se apaga temporalmente.
- El sistema devuelve un error 5xx controlado.
- PostgreSQL se restaura.
- Las reservas vuelven a funcionar y los datos anteriores se conservan.
```

## Documentación

```text
docs/GABO.md   -> implementación, comandos, pruebas y evidencias de Gabriel
docs/JORDY.md  -> tareas exactas pendientes para Jordy
```

## Pruebas locales con Docker Compose

```powershell
docker compose up -d --build
docker compose ps
```

Endpoints locales:

- Gateway: `http://localhost:8000/docs`
- Reservas: `http://localhost:8001/docs`
- Inventario: `http://localhost:8002/docs`

Detener:

```powershell
docker compose down
```

Eliminar también los datos locales:

```powershell
docker compose down -v
```

## Siguiente paso del equipo

Jordy debe seguir `docs/JORDY.md`, trabajar desde su propia cuenta de GitHub y subir commits reales para Payment Service, Notification Service, Kubernetes y Pasarela Lenta. Después se integrará su rama con `main` y se preparará el guion final de exposición e informe.

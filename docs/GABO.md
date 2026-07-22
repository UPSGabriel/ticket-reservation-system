# Parte GABO

## Componentes

- API Gateway (`api-gateway`)
- Reservation Service (`reservation-service`)
- Inventory Service (`inventory-service`)
- PostgreSQL (`database/init.sql`)
- Docker Compose para pruebas locales
- Kubernetes multinodo con `kind`
- Pruebas de resiliencia y consistencia

## Arquitectura

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

## Función de cada componente

### API Gateway

- Punto de entrada de las solicitudes.
- Rate limiting: máximo 10 solicitudes por cliente en 10 segundos.
- Bulkhead mediante semáforo para limitar concurrencia.
- Timeout y manejo de indisponibilidad del servicio de Reservas.

### Reservation Service

- Coordina Inventario, Pago y Notificación.
- Reintenta Inventario tres veces con backoff exponencial.
- Aplica fallback si Pago o Notificación no están disponibles.
- Persiste las reservas en PostgreSQL.

### Inventory Service

- Consulta y descuenta asientos.
- Ejecuta una actualización atómica condicionada por disponibilidad.
- Evita inventario negativo y sobreventa.
- Devuelve `409 Conflict` cuando no existen suficientes asientos.

### PostgreSQL

Tablas principales:

- `events`
- `inventory`
- `reservations`

## Preparar el clúster multinodo

Crear el clúster:

```powershell
kind create cluster --name ticket-cluster --config .\kind-config.yaml
```

Comprobar los dos nodos:

```powershell
kubectl config use-context kind-ticket-cluster
kubectl get nodes -o wide
```

Resultado esperado:

```text
ticket-cluster-control-plane   Ready
ticket-cluster-worker          Ready
```

## Construir y publicar imágenes

```powershell
docker login
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-images.ps1 -Action all
```

Imágenes:

```text
upsgabriel/ticket-api-gateway:1.0.0
upsgabriel/ticket-reservation-service:1.0.0
upsgabriel/ticket-inventory-service:1.0.0
```

## Desplegar en Kubernetes

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action deploy
```

El despliegue crea:

- 2 réplicas de API Gateway.
- 2 réplicas de Reservation Service.
- 2 réplicas de Inventory Service.
- 1 instancia de PostgreSQL con almacenamiento persistente.
- Services, health checks y PodDisruptionBudgets.

Consultar distribución:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action status
```

Las réplicas críticas deben estar repartidas entre:

```text
ticket-cluster-control-plane
ticket-cluster-worker
```

## Acceder a Swagger

Primero detener Docker Compose para liberar el puerto:

```powershell
docker compose down
```

Abrir el acceso al Gateway:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action forward
```

Swagger:

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

Mientras Pago no esté desplegado, el estado esperado es `PAYMENT_PENDING`. Inventario sí se descuenta y la reserva sí se guarda.

## Verificar PostgreSQL

Inventario:

```powershell
kubectl exec -n ticket-system deployment/postgres -- psql -U ticket_user -d ticket_db -c "SELECT event_id, available FROM inventory ORDER BY event_id;"
```

Reservas:

```powershell
kubectl exec -n ticket-system deployment/postgres -- psql -U ticket_user -d ticket_db -c "SELECT id, event_id, user_id, quantity, status, payment_status, notification_status, created_at FROM reservations ORDER BY created_at DESC LIMIT 10;"
```

# Escenarios prácticos GABO

## 1. Inventario Fantasma

Objetivo: eliminar una réplica de Inventario y demostrar que la réplica del otro nodo mantiene el servicio disponible mientras Kubernetes crea un reemplazo.

Ejecutar:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-inventario-fantasma.ps1
```

Durante el reinicio se crea una reserva desde Swagger. Resultado esperado:

```text
HTTP 200
inventory.status = RESERVED
```

Mecanismos demostrados:

- Réplicas multinodo.
- Service de Kubernetes.
- Recuperación automática del Deployment.
- Readiness probe.
- PodDisruptionBudget.

## 2. Condición de Carrera

Objetivo: dos usuarios intentan comprar simultáneamente el único asiento del evento 3.

Mantener activo el port-forward del Gateway y ejecutar:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-condicion-carrera.ps1
```

Resultado esperado:

```text
Usuario 301 -> HTTP 200 y RESERVED
Usuario 302 -> HTTP 409
Inventario final del evento 3 -> 0
Reservas exitosas del evento 3 -> 1
```

Mecanismo demostrado:

- Actualización SQL atómica.
- Condición `available >= quantity`.
- Prevención de sobreventa e inventario negativo.

## 3. Diluvio de Peticiones

Objetivo: enviar 15 solicitudes rápidas a una sola réplica del Gateway y comprobar la protección por rate limiting.

Ejecutar:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-diluvio-peticiones.ps1
```

Resultado esperado:

```text
Solicitudes 1-10  -> HTTP 404
Solicitudes 11-15 -> HTTP 429
Después de 11 segundos -> HTTP 404 nuevamente
```

El endpoint `/rate-test` no existe; por eso las primeras solicitudes devuelven `404`. Se utiliza únicamente para activar el middleware sin crear reservas reales. El `429` demuestra el bloqueo y el `404` final demuestra la recuperación automática al terminar la ventana.

Mecanismos demostrados:

- Rate limiting.
- Rechazo controlado con `429 Too Many Requests`.
- Protección de servicios internos.
- Recuperación automática después de la ventana temporal.

## Evidencias guardadas

1. Clúster con dos nodos `Ready`.
2. Pods distribuidos entre ambos nodos.
3. Swagger del Gateway en Kubernetes.
4. Reserva creada y descuento de inventario.
5. Reservas persistidas en PostgreSQL.
6. Pod de Inventario eliminado.
7. Reserva exitosa durante la recuperación.
8. Dos réplicas de Inventario recuperadas.
9. Condición de carrera: respuestas `200` y `409`.
10. PostgreSQL con inventario `0` y una sola reserva exitosa.
11. Rate limiting: solicitudes 11 a 15 con `429`.
12. Log `Solicitud rechazada por rate limiting` y recuperación con `404`.

## Guion corto

> Mi parte implementa la ruta principal de reservas. El cliente entra por el API Gateway, donde aplicamos rate limiting y bulkhead. El Gateway llama al Reservation Service, que coordina Inventario y persiste la reserva en PostgreSQL. Inventario realiza un descuento atómico para evitar vender dos veces el último asiento. En Kubernetes desplegamos dos réplicas de los componentes críticos distribuidas entre dos nodos. Demostramos la caída de una réplica de Inventario sin interrumpir el servicio, una condición de carrera donde solo un comprador obtiene el último asiento y un diluvio de peticiones donde el Gateway bloquea el exceso con código 429 y luego se recupera automáticamente.

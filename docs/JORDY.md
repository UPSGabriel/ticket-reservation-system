# Parte JORDY

Este documento indica exactamente qué falta para completar la parte de Jordy sin modificar la parte GABO que ya está funcionando.

## Objetivo

Completar los dos microservicios pendientes e integrarlos con Kubernetes:

- Payment Service (`payment-service`)
- Notification Service (`notification-service`)

Después se debe ejecutar el cuarto escenario práctico oficial: **Pasarela Lenta**.

## Antes de comenzar

```powershell
git pull origin main
git checkout -b jordy-servicios
```

No cambiar estos componentes salvo que sea necesario para integración:

- `api-gateway`
- `reservation-service`
- `inventory-service`
- `database`
- `k8s/gabo`

## 1. Payment Service

### Archivos a completar

```text
payment-service/app/main.py
payment-service/requirements.txt
payment-service/Dockerfile
```

### Endpoints mínimos

```text
GET  /
GET  /health
POST /payments/process
```

### Solicitud esperada

```json
{
  "reservation_id": "uuid-de-la-reserva",
  "user_id": 101,
  "amount": 20.0
}
```

### Respuesta normal esperada

```json
{
  "status": "APPROVED",
  "reservation_id": "uuid-de-la-reserva",
  "transaction_id": "uuid-del-pago",
  "amount": 20.0,
  "instance": "nombre-del-pod"
}
```

### Variables de entorno requeridas

```text
INSTANCE_NAME
PAYMENT_DELAY_SECONDS
PAYMENT_FAILURE_MODE
```

Comportamiento:

- `PAYMENT_DELAY_SECONDS=0`: respuesta normal.
- `PAYMENT_DELAY_SECONDS=20`: simula Pasarela Lenta.
- `PAYMENT_FAILURE_MODE=reject`: devuelve un rechazo controlado.

El servicio debe registrar en logs cuándo inicia el pago, cuánto tarda y cuál fue el resultado.

## 2. Notification Service

### Archivos a completar

```text
notification-service/app/main.py
notification-service/requirements.txt
notification-service/Dockerfile
```

### Endpoints mínimos

```text
GET  /
GET  /health
POST /notifications/send
```

### Solicitud esperada

```json
{
  "reservation_id": "uuid-de-la-reserva",
  "user_id": 101,
  "message": "Su reserva fue confirmada."
}
```

### Respuesta normal esperada

```json
{
  "status": "SENT",
  "reservation_id": "uuid-de-la-reserva",
  "notification_id": "uuid-de-la-notificacion",
  "instance": "nombre-del-pod"
}
```

### Variables de entorno requeridas

```text
INSTANCE_NAME
NOTIFICATION_DELAY_SECONDS
NOTIFICATION_FAILURE_MODE
```

Comportamiento:

- Respuesta normal cuando no hay fallo.
- Simulación de demora configurable.
- `NOTIFICATION_FAILURE_MODE=drop`: simula Correo Perdido.

## 3. Imágenes Docker

Construir y publicar desde su propia sesión de Docker Hub o usando las etiquetas acordadas por el equipo:

```powershell
docker build -t upsgabriel/ticket-payment-service:1.0.0 .\payment-service
docker build -t upsgabriel/ticket-notification-service:1.0.0 .\notification-service

docker push upsgabriel/ticket-payment-service:1.0.0
docker push upsgabriel/ticket-notification-service:1.0.0
```

## 4. Kubernetes

Crear un manifiesto separado:

```text
k8s/jordy/all.yaml
```

Debe incluir para cada servicio:

- Deployment.
- Service ClusterIP.
- Dos réplicas.
- Readiness probe en `/health`.
- Liveness probe en `/health`.
- Recursos requests/limits.
- Distribución entre los dos nodos.
- Variable `INSTANCE_NAME` tomada de `metadata.name`.

Nombres DNS internos que ya espera Reservation Service:

```text
http://payment-service:8003
http://notification-service:8004
```

Puertos:

```text
Payment Service      8003
Notification Service 8004
```

## 5. Cuarto fallo práctico oficial: Pasarela Lenta

### Preparación

Configurar Payment Service con:

```text
PAYMENT_DELAY_SECONDS=20
```

Reservation Service tiene un timeout corto para Pago. La reserva debe continuar con fallback en lugar de quedarse bloqueada.

### Resultado esperado

```text
Solicitud al Gateway -> HTTP 200
status                -> PAYMENT_PENDING
payment.status        -> PAYMENT_PENDING
Inventario            -> descontado
Reserva               -> persistida en PostgreSQL
```

### Evidencias

1. Configuración de demora del Payment Service.
2. Log de Payment Service mostrando la espera.
3. Log de Reservation Service mostrando timeout o indisponibilidad.
4. Respuesta `PAYMENT_PENDING`.
5. Reserva persistida en PostgreSQL.
6. Restauración de `PAYMENT_DELAY_SECONDS=0`.
7. Nueva reserva con pago `CONFIRMED`.

## 6. Correo Perdido

Este escenario puede quedar como análisis teórico o como prueba adicional.

Si se implementa prácticamente:

- Configurar `NOTIFICATION_FAILURE_MODE=drop`.
- El pago debe confirmarse.
- La reserva no debe perderse.
- El estado debe indicar `NOTIFICATION_PENDING`.
- Explicar que la notificación es secundaria frente a la reserva y el pago.

## 7. Commits reales recomendados

Jordy debe realizar y subir sus propios cambios desde su cuenta. Secuencia sugerida:

```text
Implementar Payment Service
Agregar simulación de latencia en pagos
Implementar Notification Service
Agregar manifiestos Kubernetes de servicios externos
Agregar escenario Pasarela Lenta
Documentar pruebas parte JORDY
```

Ejemplo:

```powershell
git add payment-service
git commit -m "Implementar Payment Service"

git add notification-service
git commit -m "Implementar Notification Service"

git add k8s/jordy
git commit -m "Desplegar pagos y notificaciones en Kubernetes"

git push -u origin jordy-servicios
```

Después debe abrir un Pull Request hacia `main` o coordinar la integración con Gabriel.

## 8. Criterio de finalización

La parte JORDY estará completa cuando:

- Payment Service responda normalmente.
- Notification Service responda normalmente.
- Ambos estén desplegados con dos réplicas en Kubernetes.
- Reservation Service pueda resolver sus nombres internos.
- Una reserva normal termine en `CONFIRMED`.
- Pasarela Lenta termine en `PAYMENT_PENDING` sin bloquear el sistema.
- Existan logs, capturas y commits reales de Jordy.

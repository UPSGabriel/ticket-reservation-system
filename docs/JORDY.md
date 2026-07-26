# Parte JORDY

## Estado

Jordy implement? Payment Service, Notification Service, sus im?genes, pruebas autom?ticas, manifiestos Kubernetes y el escenario reproducible Pasarela Lenta.

La validaci?n operativa final requiere que las im?genes est?n publicadas y que el cl?ster Kubernetes de dos nodos est? disponible.

## Payment Service

Archivos:

```text
payment-service/app/main.py
payment-service/requirements.txt
payment-service/Dockerfile
payment-service/tests/test_main.py
```

Endpoints:

```text
GET  /
GET  /health
POST /payments/process
```

Variables:

```text
INSTANCE_NAME
PAYMENT_DELAY_SECONDS
PAYMENT_FAILURE_MODE
PAYMENT_MIN_DELAY_MS
PAYMENT_MAX_DELAY_MS
PAYMENT_FAILURE_RATE
```

Reglas:

- Si `PAYMENT_DELAY_SECONDS` es mayor que cero, la demora fija tiene prioridad.
- Con demora fija en cero, se elige una latencia aleatoria entre el m?nimo y m?ximo.
- `PAYMENT_FAILURE_MODE=reject` fuerza HTTP 402 con `REJECTED`.
- `PAYMENT_FAILURE_RATE` acepta valores entre 0 y 1 para fallos aleatorios.
- El comportamiento normal devuelve HTTP 200 con `APPROVED`.

## Notification Service

Archivos:

```text
notification-service/app/main.py
notification-service/requirements.txt
notification-service/Dockerfile
notification-service/tests/test_main.py
```

Endpoints:

```text
GET  /
GET  /health
POST /notifications/send
```

Variables:

```text
INSTANCE_NAME
NOTIFICATION_DELAY_SECONDS
NOTIFICATION_FAILURE_MODE
NOTIFICATION_MIN_DELAY_MS
NOTIFICATION_MAX_DELAY_MS
NOTIFICATION_FAILURE_RATE
```

Reglas:

- La demora fija tiene prioridad sobre el rango aleatorio.
- `NOTIFICATION_FAILURE_MODE=drop` fuerza HTTP 503 con `DROPPED`.
- `NOTIFICATION_FAILURE_RATE` permite simular correos perdidos aleatoriamente.
- El comportamiento normal devuelve HTTP 200 con `SENT`.

## Validaci?n autom?tica

```powershell
Push-Location .\payment-service
python -m unittest discover -s tests -v
Pop-Location

Push-Location .\notification-service
python -m unittest discover -s tests -v
Pop-Location
```

## Docker

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-images.ps1 -Action build
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-images.ps1 -Action test
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-images.ps1 -Action push
```

Im?genes:

```text
upsgabriel/ticket-payment-service:1.0.0
upsgabriel/ticket-notification-service:1.0.0
```

## Kubernetes

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action deploy
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action status
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action dns
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action logs
```

El manifiesto `k8s/jordy/all.yaml` no crea ni elimina el namespace `ticket-system`. Cada servicio usa dos r?plicas, probes, recursos y distribuci?n preferida entre nodos.

## Pasarela Lenta

Mantener el Gateway en `http://localhost:8000` y ejecutar:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\jordy-pasarela-lenta.ps1
```

El script comprueba:

1. Reserva normal `CONFIRMED`.
2. Demora fija de 20 segundos.
3. Fallback `PAYMENT_PENDING` antes de cinco segundos.
4. Logs de Payment y Reservation.
5. Persistencia en PostgreSQL.
6. Restauraci?n a demora cero.
7. Nueva reserva `CONFIRMED`.

## Correo Perdido

La implementaci?n pr?ctica est? disponible mediante:

```powershell
kubectl set env deployment/notification-service -n ticket-system NOTIFICATION_FAILURE_MODE=drop NOTIFICATION_FAILURE_RATE=0
kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

Una reserva pagada debe terminar como `NOTIFICATION_PENDING`, sin perder el pago ni el registro. Restaurar con:

```powershell
kubectl set env deployment/notification-service -n ticket-system NOTIFICATION_FAILURE_MODE=none NOTIFICATION_FAILURE_RATE=0.05
kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

## Criterio de cierre operativo

La implementaci?n est? lista. Para cerrar la evidencia deben ejecutarse todav?a:

- Publicaci?n de las im?genes desde la cuenta autorizada.
- Despliegue real con dos r?plicas.
- Verificaci?n DNS.
- Reserva normal `CONFIRMED`.
- Pasarela Lenta `PAYMENT_PENDING`.
- Capturas y logs indicados en `docs/EVIDENCIAS.md`.

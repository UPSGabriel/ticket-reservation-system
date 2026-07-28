# Parte JORDY

## Responsabilidades principales

Jordy implementó y validó principalmente:

- Payment Service.
- Notification Service.
- pruebas automáticas de ambos servicios.
- imágenes Docker de Payment y Notification.
- manifiestos Kubernetes de ambos servicios.
- simulación configurable de latencia y fallos.
- escenario práctico Pasarela Lenta.
- apoyo en documentación, evidencias y demo.
- configuración del worker `jordy-node` en el clúster K3s final.

La validación operativa final quedó completada en **DigitalOcean + K3s** con dos nodos reales del clúster.

## Payment Service

Archivos principales:

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

- si `PAYMENT_DELAY_SECONDS > 0`, la demora fija tiene prioridad;
- con demora fija en cero, se elige una latencia aleatoria entre mínimo y máximo;
- `PAYMENT_FAILURE_MODE=reject` fuerza rechazo del pago;
- `PAYMENT_FAILURE_RATE` permite fallos aleatorios entre 0 y 1;
- el comportamiento normal devuelve `APPROVED`.

## Notification Service

Archivos principales:

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

- la demora fija tiene prioridad sobre el rango aleatorio;
- `NOTIFICATION_FAILURE_MODE=drop` permite forzar pérdida de notificación;
- `NOTIFICATION_FAILURE_RATE` permite simular fallos aleatorios;
- el comportamiento normal devuelve `SENT`.

## Validación automática

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

Imágenes finales:

```text
upsgabriel/ticket-payment-service:1.0.0
upsgabriel/ticket-notification-service:1.0.0
```

## Kubernetes / K3s

El manifiesto principal es:

```text
k8s/jordy/all.yaml
```

Payment y Notification usan:

- 2 réplicas;
- probes;
- límites/solicitudes de recursos;
- Services internos;
- distribución preferida entre hosts.

En el entorno final se desplegaron con:

```bash
kubectl apply -f k8s/jordy/all.yaml
kubectl get pods -n ticket-system -o wide
```

## Worker `jordy-node`

La segunda VM participa activamente como K3s agent/worker.

Comandos de evidencia ejecutados desde la propia VM:

```bash
hostname
systemctl status k3s-agent --no-pager
k3s crictl ps
```

Se verificó:

```text
hostname              Jordy-node
k3s-agent             active (running)
workloads             Running
```

En `k3s crictl ps` se observaron contenedores de Reservation, Inventory, Payment, Notification, PostgreSQL y API Gateway ejecutándose en ese nodo.

## Pasarela Lenta

Este es el escenario práctico principal de la parte Jordy.

### Preparación estable

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=0 PAYMENT_FAILURE_MODE=none PAYMENT_FAILURE_RATE=0

kubectl set env deployment/notification-service -n ticket-system \
  NOTIFICATION_FAILURE_MODE=none NOTIFICATION_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

### Inyección

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=20 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
```

### Resultado final verificado

```text
Antes:
  reserva -> CONFIRMED

Durante:
  Payment espera 20 s
  Reservation aplica timeout a los 3 s
  reserva -> PAYMENT_PENDING
  inventario -> RESERVED
  notificación -> NOT_SENT
  fila PostgreSQL -> persistida

Después:
  PAYMENT_DELAY_SECONDS=0
  nueva reserva -> CONFIRMED
```

Los logs de Payment mostraron explícitamente:

```text
esperara 20.000 segundos. origen=fixed
```

Los logs de Reservation mostraron la activación del fallback y la creación de la reserva `PAYMENT_PENDING`.

## Correo Perdido

La simulación está implementada aunque este escenario quedó dentro de los dos fallos teóricos de la selección oficial.

Ejemplo:

```bash
kubectl set env deployment/notification-service -n ticket-system \
  NOTIFICATION_FAILURE_MODE=drop \
  NOTIFICATION_FAILURE_RATE=0

kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

Una reserva pagada puede conservarse como `NOTIFICATION_PENDING` sin perder el pago ni el registro.

Restauración:

```bash
kubectl set env deployment/notification-service -n ticket-system \
  NOTIFICATION_FAILURE_MODE=none \
  NOTIFICATION_FAILURE_RATE=0

kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

## Participación en la alta disponibilidad

Durante la prueba de `kubectl drain gabriel-node`, `jordy-node` mantuvo las réplicas sobrevivientes y PostgreSQL.

Se verificó desde el Gateway sobreviviente una reserva completa:

```text
Reservation   CONFIRMED
Inventory     RESERVED
Payment       APPROVED
Notification  SENT
```

Esto demostró que el worker no era una VM pasiva: ejecutó el flujo completo mientras `gabriel-node` estaba retirado de la planificación.

## Estado final de la parte JORDY

```text
COMPLETO  Payment Service
COMPLETO  Notification Service
COMPLETO  tests
COMPLETO  imágenes Docker
COMPLETO  manifiestos Kubernetes
COMPLETO  K3s worker jordy-node
COMPLETO  DNS interno
COMPLETO  Pasarela Lenta
COMPLETO  logs y persistencia
COMPLETO  recuperación
COMPLETO  participación en prueba de drain
```

## Guion corto

> Mi parte implementa Payment y Notification como servicios independientes y configurables. Payment puede simular latencia o rechazo y Notification puede simular pérdida del envío. En Pasarela Lenta configuramos 20 segundos de demora; Reservation no se bloquea, aplica un timeout a los 3 segundos y persiste la reserva como PAYMENT_PENDING. Además, `jordy-node` funciona como worker real de K3s y durante el drain de Gabriel mantuvo los servicios y PostgreSQL necesarios para completar una reserva CONFIRMED.

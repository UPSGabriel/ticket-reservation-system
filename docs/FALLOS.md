# Catálogo de los seis fallos

## Selección

Los cuatro fallos prácticos oficiales son:

1. Inventario Fantasma.
2. Pasarela Lenta.
3. Diluvio de Peticiones.
4. Condición de Carrera.

Los dos fallos reservados para análisis y diseño son Base de Datos Intermitente y Correo Perdido. La prueba adicional de base de datos no cambia esta selección.

## Mapeo de inyección y defensa

| Fallo | Tipo | Inyección controlada | Defensa implementada o propuesta | Evidencia principal |
|---|---|---|---|---|
| Inventario Fantasma | Disponibilidad | Eliminar un pod de Inventory con `kubectl delete pod` | Dos réplicas, Service, retry con backoff y autorrecuperación de Kubernetes | Pod eliminado, segunda réplica atendiendo y pod recreado |
| Pasarela Lenta | Latencia | `PAYMENT_DELAY_SECONDS=20` mediante `kubectl set env` | Timeout de 3 s y fallback `PAYMENT_PENDING` | Timeout, log de 20 s y fila persistida |
| Diluvio de Peticiones | Sobrecarga | 15 solicitudes al mismo pod de Gateway | Rate limiting por ventana y bulkhead | 10 solicitudes admitidas por middleware, 5 HTTP 429 y recuperación |
| Base de Datos Intermitente | Conectividad | Escalar PostgreSQL temporalmente a cero; en producción se usaría pérdida de red | Error 5xx controlado; propuesta: HA, retry seguro, circuit breaker e idempotencia | Análisis teórico y prueba adicional disponible |
| Correo Perdido | Fallo no crítico | `NOTIFICATION_FAILURE_MODE=drop` o caída del servicio | Fallback `NOTIFICATION_PENDING`; propuesta: Transactional Outbox, cola, retries y DLQ | Análisis teórico y reserva conservada |
| Condición de Carrera | Consistencia | Dos solicitudes concurrentes por el último asiento | Descuento atómico condicionado en PostgreSQL | Un HTTP 200, un HTTP 409 e inventario final 0 |

---

## 1. Inventario Fantasma

### Qué se prueba

La pérdida de una réplica de Inventory no debe volver indisponible el sistema mientras exista otra réplica sana.

### Inyección final en K3s

```bash
kubectl get pods -n ticket-system -l app=inventory-service -o wide

POD=$(kubectl get pods -n ticket-system \
  -l app=inventory-service \
  --field-selector spec.nodeName=gabriel-node \
  -o jsonpath='{.items[0].metadata.name}')

kubectl delete pod "$POD" -n ticket-system
```

Inmediatamente se envía otra reserva por el Gateway.

### Resultado observado

- La réplica de `gabriel-node` fue eliminada.
- La solicitud fue atendida por la réplica de Inventory en `jordy-node`.
- La reserva terminó `CONFIRMED`.
- Kubernetes creó automáticamente una nueva réplica.
- El Deployment regresó a dos pods `1/1 Running`.

### Por qué funciona

Las réplicas proporcionan disponibilidad y el Service desacopla al consumidor del pod concreto. Reservation además aplica retry con backoff ante fallos transitorios de Inventory.

Un fallback que confirmara una compra sin consultar inventario sería incorrecto porque permitiría sobreventa.

---

## 2. Pasarela Lenta

### Qué se prueba

Payment puede degradarse por latencia sin bloquear la reserva indefinidamente.

### Inyección final en K3s

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=20 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
```

Comprobación:

```bash
kubectl get deployment payment-service -n ticket-system \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="PAYMENT_DELAY_SECONDS")].value}{"\n"}'
```

Debe devolver `20`.

### Resultado observado

- Inventory reservó el asiento.
- Reservation esperó Payment hasta su timeout de 3 s.
- La respuesta terminó `PAYMENT_PENDING`.
- Notification quedó `NOT_SENT`.
- Los logs de Reservation mostraron el fallback.
- Los logs de Payment mostraron `esperara 20.000 segundos. origen=fixed`.
- PostgreSQL conservó la fila con `PAYMENT_PENDING / PAYMENT_PENDING / NOT_SENT`.
- Después de restaurar `PAYMENT_DELAY_SECONDS=0`, una nueva reserva volvió a `CONFIRMED`.

### Por qué funciona

El timeout evita mantener la operación bloqueada durante la degradación. El fallback conserva la intención de negocio para procesamiento posterior.

No se reintenta el cobro inmediatamente porque, sin idempotencia, un retry podría generar cobros duplicados.

### Recuperación

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=0 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
```

---

## 3. Diluvio de Peticiones

### Qué se prueba

El Gateway debe protegerse cuando un cliente excede el número permitido de solicitudes en una ventana temporal.

### Inyección final en K3s

Se elige un pod específico del Gateway para evitar que el balanceo reparta las solicitudes entre dos contadores independientes.

```bash
kubectl get pods -n ticket-system -l app=api-gateway -o wide
```

Port-forward al pod seleccionado:

```bash
kubectl port-forward pod/<POD_GATEWAY> 8005:8000 \
  -n ticket-system --address 127.0.0.1
```

En otra terminal:

```bash
for i in $(seq 1 15); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8005/rate-test)
  echo "Solicitud $i -> HTTP $code"
done
```

### Resultado observado

```text
Solicitudes 1–10   HTTP 404
Solicitudes 11–15  HTTP 429
```

`/rate-test` no existe, por eso las primeras respuestas son 404; aun así atraviesan el middleware y consumen la ventana del limitador.

Los logs mostraron cinco veces:

```text
Solicitud rechazada por rate limiting.
```

Después de esperar 11 s, una nueva solicitud volvió a HTTP 404, demostrando recuperación automática de la ventana.

### Por qué funciona

Rate limiting controla admisión por cliente/ventana. El bulkhead limita simultaneidad interna y evita que todas las solicitudes ocupen los recursos del Gateway.

Escalar réplicas ayuda con capacidad, pero no sustituye el control de admisión ante carga ilimitada.

---

## 4. Condición de Carrera

### Qué se prueba

Dos usuarios intentan reservar al mismo tiempo el último asiento. Solo uno debe obtenerlo.

### Preparación

```bash
kubectl exec -n ticket-system deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "UPDATE inventory SET available=1,updated_at=CURRENT_TIMESTAMP WHERE event_id=3; SELECT event_id,available FROM inventory WHERE event_id=3;"
```

### Inyección

Se lanzan dos `curl` en segundo plano de forma concurrente contra el mismo evento.

### Resultado observado

```text
Usuario 301 -> HTTP 200 -> CONFIRMED
Usuario 302 -> HTTP 409 -> sin asiento
```

El usuario ganador puede cambiar entre ejecuciones. La propiedad que debe mantenerse es que exista un solo ganador.

Consulta final:

```bash
kubectl exec -n ticket-system deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "SELECT event_id,available FROM inventory WHERE event_id=3; SELECT user_id,event_id,quantity,status FROM reservations WHERE event_id=3 AND user_id IN (301,302) ORDER BY created_at DESC;"
```

Resultado final:

```text
available = 0
una única reserva CONFIRMED
```

### Por qué funciona

La operación atómica en PostgreSQL combina verificación y descuento en una sentencia condicionada. La base actúa como árbitro consistente y evita que dos transacciones descuenten el mismo último asiento.

Un retry no arreglaría esta carrera; incluso podría empeorarla.

---

# Prueba adicional: disponibilidad ante retirada de nodo

Además de los cuatro fallos oficiales se verificó una prueba de infraestructura:

```bash
kubectl drain gabriel-node --ignore-daemonsets --delete-emptydir-data
```

Durante el drain:

- `gabriel-node` quedó `Ready,SchedulingDisabled`.
- Las réplicas sobrevivientes permanecieron en `jordy-node`.
- PostgreSQL permaneció disponible en `jordy-node`.
- Se abrió un port-forward al Gateway sobreviviente.
- Una reserva completa terminó `CONFIRMED`.

Recuperación:

```bash
kubectl uncordon gabriel-node
```

Después se verificó el regreso de capacidad y una nueva reserva `CONFIRMED`.

Esta es una retirada controlada de workloads, no un apagado abrupto del único control-plane.

---

## Scripts locales conservados

Los scripts PowerShell originales permanecen en `chaos/` para ejecución local/KIND y como referencia automatizada:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-inventario-fantasma.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\jordy-pasarela-lenta.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-diluvio-peticiones.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-condicion-carrera.ps1
```

La evidencia final, sin embargo, se obtuvo ejecutando los comandos equivalentes directamente en Ubuntu/K3s sobre DigitalOcean.

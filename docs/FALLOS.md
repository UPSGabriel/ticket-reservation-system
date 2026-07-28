# Catálogo de los seis fallos

## Selección de la práctica

Los cuatro fallos prácticos oficiales son:

1. **Inventario Fantasma**.
2. **Pasarela Lenta**.
3. **Diluvio de Peticiones**.
4. **Condición de Carrera**.

Los dos fallos reservados para análisis y diseño son:

5. **Base de Datos Intermitente**.
6. **Correo Perdido**.

La evidencia final se obtuvo sobre el clúster K3s de dos nodos en DigitalOcean. Los scripts PowerShell originales se conservan como referencia del entorno local/KIND, mientras los scripts `k3s-*.sh` son los correspondientes a la infraestructura final.

---

## Mapeo de inyección y defensa

| Fallo | Tipo | Mecanismo de inyección en Kubernetes/K3s | Defensa implementada o propuesta | Evidencia principal |
|---|---|---|---|---|
| Inventario Fantasma | Disponibilidad | `kubectl delete pod` sobre una réplica de Inventory | 2 réplicas, Service, retry con backoff, readiness y autorrecuperación | Reserva `CONFIRMED` con la otra réplica y pod recreado |
| Pasarela Lenta | Latencia | `kubectl set env` con `PAYMENT_DELAY_SECONDS=20` y rollout | timeout de 3 s + fallback `PAYMENT_PENDING` + persistencia | respuesta controlada, logs de 20 s y fila en PostgreSQL |
| Diluvio de Peticiones | Sobrecarga | ráfaga de 15 solicitudes contra una misma réplica del Gateway | rate limiting por ventana + bulkhead de concurrencia | solicitudes 11–15 con HTTP 429, logs y recuperación de ventana |
| Base de Datos Intermitente | Conectividad | **propuesto:** alternar una `NetworkPolicy` de denegación o un proxy de red tipo Toxiproxy para crear flapping real | HA de PostgreSQL, retry seguro con jitter, circuit breaker e idempotencia | análisis teórico y diseño de producción |
| Correo Perdido | Fallo no crítico | `NOTIFICATION_FAILURE_MODE=drop` o indisponibilidad del Service | fallback `NOTIFICATION_PENDING`; producción: Transactional Outbox, cola, retries y DLQ | análisis teórico y conservación de la reserva |
| Condición de Carrera | Consistencia | dos clientes concurrentes intentan comprar el último asiento | actualización SQL atómica condicionada | un HTTP 200, un HTTP 409, inventario final 0 |

> La prueba adicional que escala PostgreSQL a cero representa **indisponibilidad total**, no flapping. Se conserva como experimento adicional de laboratorio, pero no se presenta como mecanismo principal de inyección de Base de Datos Intermitente.

---

# Scripts finales para DigitalOcean + K3s

Ejecutar desde `gabriel-node`, dentro del repositorio. Para los escenarios que consumen el Gateway debe existir un `port-forward` principal en `127.0.0.1:8000`, excepto Diluvio, que abre su propio port-forward a un pod concreto.

```bash
bash chaos/k3s-inventario-fantasma.sh
bash chaos/k3s-pasarela-lenta.sh
bash chaos/k3s-diluvio-peticiones.sh
bash chaos/k3s-condicion-carrera.sh
```

Cada script imprime estado inicial, inyección, evidencia y resultado final. Los scripts usan `set -Eeuo pipefail` para fallar explícitamente si una expectativa principal no se cumple.

---

## 1. Inventario Fantasma

### Qué se prueba

La pérdida de una réplica de Inventory no debe volver indisponible el sistema mientras exista otra réplica sana en el segundo nodo.

### Inyección

```bash
POD=$(kubectl get pods -n ticket-system \
  -l app=inventory-service \
  --field-selector spec.nodeName=gabriel-node \
  -o jsonpath='{.items[0].metadata.name}')

kubectl delete pod "$POD" -n ticket-system
```

### Resultado observado

- se eliminó la réplica de `gabriel-node`;
- la réplica de Inventory en `jordy-node` continuó disponible;
- una reserva realizada durante el fallo terminó `CONFIRMED`;
- Kubernetes creó automáticamente un nuevo pod;
- el Deployment regresó a dos réplicas disponibles.

### Justificación de la defensa

La replicación aporta disponibilidad y el Service desacopla a Reservation de una instancia concreta. Reservation además realiza hasta tres intentos con backoff ante fallos transitorios de Inventory. Un fallback que confirmara la compra sin consultar inventario sería incorrecto porque podría producir sobreventa.

---

## 2. Pasarela Lenta

### Qué se prueba

Payment tarda deliberadamente 20 segundos. Reservation no debe mantener la solicitud bloqueada durante todo ese tiempo.

### Inyección

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=20 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
```

### Resultado observado

- Inventory reservó el asiento;
- Reservation aplicó un timeout de 3 segundos al llamado a Payment;
- la reserva respondió como `PAYMENT_PENDING`;
- Notification quedó `NOT_SENT` porque el pago todavía no estaba confirmado;
- Payment registró en logs `esperara 20.000 segundos`;
- PostgreSQL conservó la reserva con `PAYMENT_PENDING / PAYMENT_PENDING / NOT_SENT`;
- al restaurar `PAYMENT_DELAY_SECONDS=0`, una nueva reserva volvió a `CONFIRMED`.

### Justificación de la defensa

El timeout limita el tiempo de espera de una dependencia lenta y el fallback conserva la intención de negocio para procesamiento posterior. No se reintenta inmediatamente un pago porque, sin una clave de idempotencia, un retry podría generar cobros duplicados.

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

Una sola instancia del Gateway recibe más solicitudes de las permitidas dentro de la ventana configurada.

### Inyección

Se selecciona un pod específico para que todas las solicitudes atraviesen el mismo contador local de rate limiting.

```bash
kubectl get pods -n ticket-system -l app=api-gateway -o wide
kubectl port-forward pod/<POD_GATEWAY> 8005:8000 -n ticket-system --address 127.0.0.1
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

`/rate-test` no existe; el 404 es intencional para atravesar el middleware sin crear reservas reales. Después de 11 segundos, la misma ruta volvió a HTTP 404, demostrando que la ventana del limitador se recuperó.

### Justificación de la defensa

Rate limiting controla la admisión por cliente/ventana. El bulkhead limita la cantidad de solicitudes concurrentes que ingresan al flujo de reservas. Escalar réplicas mejora capacidad, pero no reemplaza el control de admisión ante carga excesiva.

---

## 4. Condición de Carrera

### Qué se prueba

Dos usuarios intentan reservar simultáneamente el único asiento disponible del evento 3. Debe existir exactamente un ganador.

### Preparación

```bash
kubectl exec -n ticket-system deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "UPDATE inventory SET available=1,updated_at=CURRENT_TIMESTAMP WHERE event_id=3; SELECT event_id,available FROM inventory WHERE event_id=3;"
```

### Inyección

Se lanzan dos solicitudes `curl` en segundo plano y se espera la finalización de ambas.

### Resultado observado

```text
un usuario -> HTTP 200 -> CONFIRMED
otro usuario -> HTTP 409 -> sin asiento
inventario final -> 0
reservas CONFIRMED de la carrera -> 1
```

El usuario ganador puede variar entre ejecuciones; la propiedad importante es que solo una operación descuente el último asiento.

### Justificación de la defensa

Inventory combina verificación y descuento en una única sentencia SQL condicionada por `available >= quantity`. PostgreSQL actúa como árbitro consistente y evita inventario negativo y sobreventa. Un retry no solucionaría esta carrera.

---

# Prueba adicional: disponibilidad ante retirada de nodo

Además de los cuatro escenarios oficiales se verificó la retirada controlada de los workloads de `gabriel-node`:

```bash
kubectl drain gabriel-node --ignore-daemonsets --delete-emptydir-data
```

Durante el drain:

- `gabriel-node` quedó `Ready,SchedulingDisabled`;
- las réplicas sobrevivientes permanecieron en `jordy-node`;
- PostgreSQL permaneció disponible porque su PV `local-path` está asociado a `jordy-node`;
- una reserva completa ejecutada contra el Gateway sobreviviente terminó `CONFIRMED`.

Recuperación:

```bash
kubectl uncordon gabriel-node
```

Después se verificó el regreso de capacidad y una nueva reserva `CONFIRMED`.

Esta prueba representa una retirada controlada de workloads, no un apagado físico abrupto del único control-plane.

---

## Scripts locales conservados

Los scripts PowerShell anteriores siguen disponibles como referencia para Windows/KIND:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-inventario-fantasma.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\jordy-pasarela-lenta.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-diluvio-peticiones.ps1
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-condicion-carrera.ps1
```

Para la entrega y demo sobre DigitalOcean se deben utilizar los scripts `k3s-*.sh` o sus comandos equivalentes documentados en `docs/DEMO.md`.

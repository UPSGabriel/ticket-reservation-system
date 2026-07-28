# Guion de demo en vivo

Duración objetivo: **12 a 14 minutos**. Ambos integrantes participan activamente.

La demo final se realiza sobre el clúster **K3s de dos nodos en DigitalOcean**.

---

## Preparación antes de clase

En `Gabriel-node`:

```bash
cd ~/ticket-reservation-system
kubectl get nodes -o wide
kubectl get pods -n ticket-system -o wide
kubectl get services -n ticket-system
```

Comprobar que:

- `gabriel-node` está `Ready`.
- `jordy-node` está `Ready`.
- Los pods están `Running`.
- PostgreSQL está disponible en `jordy-node`.

Abrir el Gateway:

```bash
kubectl port-forward service/api-gateway 8000:8000 \
  -n ticket-system --address 127.0.0.1
```

En `Jordy-node`, dejar preparada otra consola con:

```bash
hostname
systemctl status k3s-agent --no-pager
k3s crictl ps
```

### Recomendación de terminales

1. Estado del clúster.
2. Port-forward del Gateway.
3. Comandos de fallos.
4. Logs/PostgreSQL.
5. Consola de `Jordy-node` para demostrar el worker.

---

## Minuto 0–2: arquitectura — Gabriel

Mostrar:

```bash
kubectl get nodes -o wide
kubectl get pods -n ticket-system -o wide
kubectl get services -n ticket-system
```

Explicar:

- dos Droplets independientes;
- `gabriel-node` como K3s server/control-plane;
- `jordy-node` como K3s agent/worker;
- cinco servicios HTTP con dos réplicas;
- PostgreSQL con una réplica y PVC `local-path`;
- comunicación interna mediante Services y DNS de Kubernetes.

Frase útil:

> El sistema no depende de IPs de pods. Cada microservicio consume el nombre estable del Service y Kubernetes resuelve la réplica disponible.

---

## Minuto 2–3: flujo normal — Jordy

Antes, estabilizar Payment y Notification:

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=0 PAYMENT_FAILURE_MODE=none PAYMENT_FAILURE_RATE=0

kubectl set env deployment/notification-service -n ticket-system \
  NOTIFICATION_FAILURE_MODE=none NOTIFICATION_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

Reserva normal:

```bash
curl -s -X POST http://127.0.0.1:8000/api/reservations \
  -H "Content-Type: application/json" \
  -d '{"event_id":1,"user_id":7001,"quantity":1}' \
  | python3 -m json.tool
```

Mostrar:

```text
status                 CONFIRMED
inventory              RESERVED
payment                APPROVED
notification           SENT
```

---

## Minuto 3–5: Inventario Fantasma — Gabriel

Antes:

```bash
kubectl get pods -n ticket-system -l app=inventory-service -o wide
```

Elegir la réplica de `gabriel-node` y eliminarla:

```bash
POD=$(kubectl get pods -n ticket-system \
  -l app=inventory-service \
  --field-selector spec.nodeName=gabriel-node \
  -o jsonpath='{.items[0].metadata.name}')

kubectl delete pod "$POD" -n ticket-system
```

Inmediatamente crear otra reserva.

Explicar:

- desaparece una réplica;
- el Service todavía tiene otra instancia sana;
- la reserva continúa `CONFIRMED`;
- Kubernetes recrea el pod perdido.

Después:

```bash
kubectl get pods -n ticket-system -l app=inventory-service -o wide
```

---

## Minuto 5–8: Pasarela Lenta — Jordy

Inyectar 20 segundos:

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=20 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
```

Comprobar:

```bash
kubectl get deployment payment-service -n ticket-system \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="PAYMENT_DELAY_SECONDS")].value}{"\n"}'
```

Debe aparecer `20`.

Crear reserva y mostrar:

```text
status               PAYMENT_PENDING
inventory            RESERVED
payment              PAYMENT_PENDING
notification         NOT_SENT
```

Explicar:

- Payment tarda 20 s;
- Reservation tiene timeout de 3 s;
- la reserva no se pierde;
- queda persistida como `PAYMENT_PENDING`.

Mostrar logs:

```bash
kubectl logs -n ticket-system -l app=reservation-service --since=10m \
  --prefix=true --max-log-requests=10 \
  | grep -E "Servicio de Pagos|PAYMENT_PENDING|Reserva"

kubectl logs -n ticket-system -l app=payment-service --since=10m \
  --prefix=true --max-log-requests=10 \
  | grep -E "esperara 20\.000|resultado=APPROVED"
```

Restaurar SIEMPRE antes de seguir:

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=0 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
```

---

## Minuto 8–10: Diluvio de Peticiones — Gabriel

Elegir una sola réplica del Gateway:

```bash
kubectl get pods -n ticket-system -l app=api-gateway -o wide
```

Abrir otro port-forward directamente a ese pod:

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

Mostrar:

```text
1–10   HTTP 404
11–15  HTTP 429
```

Explicar que `/rate-test` no existe; el 404 sirve para atravesar el middleware. El resultado importante es el cambio a 429 después de alcanzar el límite.

Logs:

```bash
kubectl logs <POD_GATEWAY> -n ticket-system --since=10m \
  | grep "rate limiting"
```

Esperar 11 s y comprobar que deja de responder 429.

---

## Minuto 10–12: Condición de Carrera — Gabriel y Jordy

Gabriel explica el escenario: queda un solo asiento.

Preparar:

```bash
kubectl exec -n ticket-system deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "UPDATE inventory SET available=1,updated_at=CURRENT_TIMESTAMP WHERE event_id=3; SELECT event_id,available FROM inventory WHERE event_id=3;"
```

Jordy lanza las dos solicitudes concurrentes.

Resultado esperado:

```text
un usuario -> HTTP 200 -> CONFIRMED
otro       -> HTTP 409
inventario final -> 0
```

Explicar:

> La base de datos actúa como árbitro. El descuento se hace de forma atómica y no permite que el inventario termine en -1.

---

## Minuto 12–14: alta disponibilidad y cierre — ambos

Esta prueba es opcional si el tiempo es muy justo, pero es la evidencia más fuerte del carácter multinodo.

### Antes

```bash
kubectl get nodes
kubectl get pods -n ticket-system -o wide
```

### Gabriel drena su nodo

```bash
kubectl drain gabriel-node --ignore-daemonsets --delete-emptydir-data
```

Mostrar:

```text
gabriel-node   Ready,SchedulingDisabled
jordy-node     Ready
```

### Jordy demuestra que su worker sigue vivo

En la consola de `Jordy-node`:

```bash
hostname
systemctl status k3s-agent --no-pager
k3s crictl ps
```

### Reserva usando el Gateway sobreviviente

Buscar el Gateway de `jordy-node`:

```bash
kubectl get pods -n ticket-system -l app=api-gateway -o wide
```

Port-forward:

```bash
kubectl port-forward pod/<POD_GATEWAY_JORDY> 8006:8000 \
  -n ticket-system --address 127.0.0.1
```

Reserva:

```bash
curl -s -X POST http://127.0.0.1:8006/api/reservations \
  -H "Content-Type: application/json" \
  -d '{"event_id":1,"user_id":7005,"quantity":1}' \
  | python3 -m json.tool
```

Mostrar `CONFIRMED` y explicar que los servicios sobrevivientes están en `jordy-node`.

### Recuperar

```bash
kubectl uncordon gabriel-node
sleep 10
kubectl get nodes
kubectl get pods -n ticket-system -o wide
```

Frase final sugerida:

> No buscamos que el sistema nunca falle. Diseñamos cada componente para que falle de forma controlada, mantenga consistencia y recupere capacidad automáticamente.

---

# Plan de contingencia

- Guardar todas las capturas antes de la clase.
- Mantener el port-forward principal en una terminal que no se reutilice.
- Si un port-forward muere porque el pod fue eliminado o drenado, crear uno nuevo hacia un pod `Running`.
- Si el Gateway devuelve 429 durante otra prueba, esperar 11 segundos.
- Si el evento 1 se queda sin inventario, restablecerlo desde PostgreSQL o usar otro evento preparado.
- Después de Pasarela Lenta, verificar siempre que `PAYMENT_DELAY_SECONDS=0`.
- No drenar `jordy-node` en esta arquitectura: PostgreSQL y su volumen `local-path` están asociados a ese nodo.
- Si después de `uncordon` dos réplicas quedan temporalmente en el mismo nodo, comprobar que el servicio está sano; la afinidad configurada es preferida, no una garantía absoluta.
- No afirmar que `drain` equivale a un apagado físico abrupto: es una retirada controlada de workloads.

No se necesita Kubernetes Dashboard ni Grafana. Las salidas de terminal, logs, respuestas JSON y filas PostgreSQL son la evidencia utilizada por el proyecto.

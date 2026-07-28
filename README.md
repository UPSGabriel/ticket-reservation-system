# 🎟️ Ticket Reservation System

Sistema distribuido de reservas de entradas construido con **FastAPI**, **PostgreSQL**, **Docker** y **Kubernetes/K3s**, diseñado para demostrar tolerancia a fallos, recuperación automática, control de sobrecarga y consistencia bajo concurrencia.

## 👥 Integrantes

- Gabriel Córdova
- Jordy Espinoza

## ✅ Estado final

La práctica quedó desplegada y verificada sobre un **clúster K3s real de dos nodos en DigitalOcean**.

- `Gabriel-node`: K3s server / control-plane y ejecución de workloads.
- `Jordy-node`: K3s agent / worker y ejecución de workloads.
- Los cinco servicios HTTP trabajan con **2 réplicas**.
- PostgreSQL trabaja con **1 réplica + PVC de 1 GiB**.
- Los servicios se descubren por **DNS interno de Kubernetes**.
- Se verificó una reserva normal `CONFIRMED`.
- Se ejecutaron los cuatro fallos prácticos oficiales.
- Se ejecutó una prueba adicional de alta disponibilidad mediante `kubectl drain gabriel-node`.
- Durante el drain, el sistema siguió procesando reservas desde `Jordy-node`.
- Después de `uncordon`, el clúster recuperó sus réplicas y volvió a procesar reservas normalmente.

> La infraestructura final de la práctica es **DigitalOcean + K3s**. El soporte KIND/PowerShell que permanece en el repositorio corresponde al entorno local de desarrollo y a las primeras etapas de la práctica.

---

## 🧩 Componentes

| Componente | Puerto | Rol | Réplicas finales |
|---|---:|---|---:|
| API Gateway | 8000 | Punto de entrada, rate limiting y bulkhead | 2 |
| Reservation Service | 8001 | Orquesta la reserva y persiste el resultado | 2 |
| Inventory Service | 8002 | Control de stock y descuento atómico | 2 |
| Payment Service | 8003 | Stub de pagos con latencia/fallos configurables | 2 |
| Notification Service | 8004 | Stub de notificaciones con fallos configurables | 2 |
| PostgreSQL | 5432 | Persistencia de inventario y reservas | 1 |

---

# 🏗️ Arquitectura final

```text
                         Cliente / curl / Swagger
                                  |
                                  v
                           +--------------+
                           | API Gateway  |
                           |    :8000     |
                           +------+-------+
                                  |
                                  v
                      +-----------------------+
                      | Reservation Service   |
                      |         :8001         |
                      +----+---------+--------+
                           |         |
                 +---------+         +------------------+
                 |                                    |
                 v                                    v
        +------------------+                  +------------------+
        | Inventory Service|                  | Payment Service  |
        |      :8002       |                  |      :8003       |
        +--------+---------+                  +------------------+
                 |
                 |                         +----------------------+
                 |                         | Notification Service |
                 |                         |        :8004         |
                 |                         +----------------------+
                 |
                 +------------------+
                                    v
                              +------------+
                              | PostgreSQL |
                              |   :5432    |
                              +------------+
```

### Infraestructura K3s

```text
DigitalOcean
│
├── Gabriel-node
│   ├── K3s server / control-plane
│   ├── kubectl
│   └── réplicas de los microservicios
│
└── Jordy-node
    ├── K3s agent / worker
    ├── réplicas de los microservicios
    └── PostgreSQL + volumen local-path
```

Los servicios HTTP usan reglas de distribución por `kubernetes.io/hostname`. En condiciones normales se busca tener una réplica en cada nodo.

### ⚠️ Nota importante sobre PostgreSQL

El PVC usa `local-path`, el provisioner por defecto de K3s. En la ejecución final el volumen quedó asociado a `Jordy-node`, por lo que la base de datos no es HA entre nodos.

Por esta razón la demostración de caída de nodo se realiza drenando **`Gabriel-node`**, manteniendo PostgreSQL disponible en `Jordy-node`.

Esto es una limitación conocida del entorno académico actual. En producción se debería usar almacenamiento compartido/replicado y una estrategia HA para PostgreSQL.

Más detalle: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

---

# 📁 Estructura del repositorio

```text
.
├── api-gateway/
├── reservation-service/
├── inventory-service/
├── payment-service/
├── notification-service/
├── db/
├── k8s/
│   ├── gabo/all.yaml
│   └── jordy/all.yaml
├── chaos/
├── scripts/
├── docs/
│   ├── ARQUITECTURA.md
│   ├── FALLOS.md
│   ├── DEMO.md
│   ├── EVIDENCIAS.md
│   └── ANALISIS-FALLOS.md
├── docker-compose.yml
├── kind-config.yaml
└── README.md
```

---

# ☁️ Montaje del clúster K3s en DigitalOcean

La práctica final utilizó dos Droplets Ubuntu.

## 1. Nodo server / control-plane

En `Gabriel-node`:

```bash
curl -sfL https://get.k3s.io | sh -
```

Comprobar:

```bash
systemctl status k3s --no-pager
kubectl get nodes -o wide
```

Obtener el token para unir el worker:

```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

> No publicar ni guardar el token del clúster en GitHub.

## 2. Nodo worker

En `Jordy-node`:

```bash
curl -sfL https://get.k3s.io | \
  K3S_URL=https://<IP_DEL_SERVER>:6443 \
  K3S_TOKEN=<TOKEN_PRIVADO> sh -
```

Comprobar desde el worker:

```bash
hostname
systemctl status k3s-agent --no-pager
k3s crictl ps
```

## 3. Ver los dos nodos desde el control-plane

```bash
kubectl get nodes -o wide
```

Resultado esperado:

```text
gabriel-node   Ready   control-plane
jordy-node     Ready   <none>
```

---

# 🚀 Despliegue

En `Gabriel-node`:

```bash
git clone https://github.com/UPSGabriel/ticket-reservation-system.git
cd ticket-reservation-system

kubectl apply -f k8s/gabo/all.yaml
kubectl apply -f k8s/jordy/all.yaml
```

Verificar:

```bash
kubectl get nodes -o wide
kubectl get deployments -n ticket-system
kubectl get pods -n ticket-system -o wide
kubectl get services -n ticket-system
```

Todos los pods deben quedar `Running` y `1/1 Ready`.

---

# 🌐 DNS interno de Kubernetes

Los microservicios se comunican usando nombres DNS de los `Service`, no IPs fijas.

```text
reservation-service -> inventory-service:8002
reservation-service -> payment-service:8003
reservation-service -> notification-service:8004
reservation-service -> postgres:5432
api-gateway         -> reservation-service:8001
```

Comprobación utilizada en el clúster final:

```bash
kubectl exec -n ticket-system deployment/reservation-service -- \
  python -c "import socket; names=['inventory-service','payment-service','notification-service','postgres']; [print(n, '->', socket.gethostbyname(n)) for n in names]"
```

En la ejecución final los cuatro nombres resolvieron correctamente a sus `ClusterIP`.

---

# 🔌 Acceso al Gateway

El Gateway se mantiene como `ClusterIP`. Para la demo se usa `port-forward`:

```bash
kubectl port-forward service/api-gateway 8000:8000 \
  -n ticket-system --address 127.0.0.1
```

En otra terminal:

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

Resultado esperado:

```json
{
  "status": "ok",
  "service": "api-gateway"
}
```

---

# 🎫 Reserva normal

Antes de una prueba determinista se desactivan fallos aleatorios de Payment y Notification:

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=0 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl set env deployment/notification-service -n ticket-system \
  NOTIFICATION_FAILURE_MODE=none \
  NOTIFICATION_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

Crear reserva:

```bash
curl -s -X POST http://127.0.0.1:8000/api/reservations \
  -H "Content-Type: application/json" \
  -d '{"event_id":1,"user_id":9001,"quantity":1}' \
  | python3 -m json.tool
```

Resultado esperado:

```text
status                    CONFIRMED
inventory.status          RESERVED
payment.detail.status     APPROVED
notification.detail.status SENT
```

---

# 💥 Chaos Engineering — 4 fallos prácticos

Los cuatro escenarios oficiales son:

1. **Inventario Fantasma** — pérdida de una réplica de Inventory.
2. **Pasarela Lenta** — Payment tarda 20 segundos.
3. **Diluvio de Peticiones** — exceso de solicitudes al Gateway.
4. **Condición de Carrera** — dos usuarios compiten por el último asiento.

Los dos escenarios restantes, **Base de Datos Intermitente** y **Correo Perdido**, se mantienen como análisis/diseño teórico según la selección de la práctica.

---

## 👻 1. Inventario Fantasma

### Objetivo

Eliminar una réplica de Inventory y demostrar que la segunda réplica mantiene el servicio y Kubernetes recrea la instancia perdida.

### Antes

```bash
kubectl get pods -n ticket-system -l app=inventory-service -o wide
```

### Inyectar fallo en la réplica de Gabriel

```bash
POD=$(kubectl get pods -n ticket-system \
  -l app=inventory-service \
  --field-selector spec.nodeName=gabriel-node \
  -o jsonpath='{.items[0].metadata.name}')

kubectl delete pod "$POD" -n ticket-system
```

### Lanzar reserva inmediatamente

```bash
curl -s -X POST http://127.0.0.1:8000/api/reservations \
  -H "Content-Type: application/json" \
  -d '{"event_id":1,"user_id":9002,"quantity":1}' \
  | python3 -m json.tool
```

Resultado verificado:

```text
pod de Gabriel eliminado
reserva                         CONFIRMED
inventory                       RESERVED
Inventory atendido por          réplica de jordy-node
```

### Recuperación

```bash
kubectl get pods -n ticket-system -l app=inventory-service -o wide
```

Kubernetes recrea automáticamente la réplica eliminada y vuelve a tener dos instancias.

**Defensa:** replicación + Service de Kubernetes + retry con backoff + autorrecuperación del Deployment.

---

## 🐌 2. Pasarela Lenta

### Objetivo

Forzar a Payment a tardar 20 s y verificar que Reservation no queda bloqueado: aplica timeout a los 3 s y persiste la reserva como `PAYMENT_PENDING`.

### Estabilizar dependencias

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=0 PAYMENT_FAILURE_MODE=none PAYMENT_FAILURE_RATE=0

kubectl set env deployment/notification-service -n ticket-system \
  NOTIFICATION_FAILURE_MODE=none NOTIFICATION_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
kubectl rollout status deployment/notification-service -n ticket-system --timeout=240s
```

### Inyectar 20 segundos de latencia

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=20 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
```

Comprobar valor:

```bash
kubectl get deployment payment-service -n ticket-system \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="PAYMENT_DELAY_SECONDS")].value}{"\n"}'
```

Debe imprimir:

```text
20
```

### Reserva durante el fallo

```bash
curl -s -X POST http://127.0.0.1:8000/api/reservations \
  -H "Content-Type: application/json" \
  -d '{"event_id":1,"user_id":9003,"quantity":1}' \
  | python3 -m json.tool
```

Resultado verificado:

```text
status               PAYMENT_PENDING
inventory.status     RESERVED
payment.status       PAYMENT_PENDING
notification.status  NOT_SENT
```

### Ver timeout/fallback en Reservation

```bash
kubectl logs -n ticket-system -l app=reservation-service --since=10m \
  --prefix=true --max-log-requests=10 \
  | grep -E "Servicio de Pagos|PAYMENT_PENDING|Reserva"
```

### Ver los 20 segundos en Payment

```bash
kubectl logs -n ticket-system -l app=payment-service --since=10m \
  --prefix=true --max-log-requests=10 \
  | grep -E "esperara 20\.000|resultado=APPROVED"
```

### Comprobar persistencia

```bash
kubectl exec -n ticket-system deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "SELECT id,user_id,status,payment_status,notification_status FROM reservations WHERE user_id=9003 ORDER BY created_at DESC LIMIT 1;"
```

Resultado esperado:

```text
PAYMENT_PENDING | PAYMENT_PENDING | NOT_SENT
```

### Recuperar Payment

```bash
kubectl set env deployment/payment-service -n ticket-system \
  PAYMENT_DELAY_SECONDS=0 \
  PAYMENT_FAILURE_MODE=none \
  PAYMENT_FAILURE_RATE=0

kubectl rollout status deployment/payment-service -n ticket-system --timeout=240s
```

Una nueva reserva debe volver a `CONFIRMED`.

**Defensa:** timeout de 3 s + fallback `PAYMENT_PENDING` + persistencia del estado.

---

## 🌊 3. Diluvio de Peticiones

### Objetivo

Enviar 15 solicitudes a una misma instancia del Gateway. El límite configurado es 10 solicitudes por una ventana de 10 s.

### Elegir un Gateway concreto

```bash
kubectl get pods -n ticket-system -l app=api-gateway -o wide
```

Abrir un port-forward al pod que se quiera probar:

```bash
kubectl port-forward pod/<POD_GATEWAY> 8005:8000 \
  -n ticket-system --address 127.0.0.1
```

### Enviar 15 solicitudes

```bash
for i in $(seq 1 15); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8005/rate-test)
  echo "Solicitud $i -> HTTP $code"
done
```

Resultado verificado:

```text
Solicitudes 1–10   HTTP 404
Solicitudes 11–15  HTTP 429
```

`/rate-test` no existe, por eso las primeras respuestas son 404. Lo importante es que atraviesan el middleware; al superar la ventana aparecen los `429 Too Many Requests`.

### Logs del rate limiting

```bash
kubectl logs <POD_GATEWAY> -n ticket-system --since=10m \
  | grep "rate limiting"
```

### Recuperación de ventana

```bash
sleep 11
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8005/rate-test
```

Después de 11 s vuelve a `HTTP 404`, demostrando que ya no está limitado.

**Defensa:** rate limiting por ventana + bulkhead de concurrencia.

---

## 🏎️ 4. Condición de Carrera

### Objetivo

Preparar exactamente un asiento y lanzar dos reservas simultáneas. Solo una debe ganar.

### Preparar un único asiento

```bash
kubectl exec -n ticket-system deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "UPDATE inventory SET available=1,updated_at=CURRENT_TIMESTAMP WHERE event_id=3; SELECT event_id,available FROM inventory WHERE event_id=3;"
```

Debe mostrar:

```text
event_id 3 | available 1
```

### Lanzar dos reservas concurrentes

```bash
curl -s -o /tmp/race301.json -w "%{http_code}" \
  -X POST http://127.0.0.1:8000/api/reservations \
  -H "Content-Type: application/json" \
  -d '{"event_id":3,"user_id":301,"quantity":1}' \
  > /tmp/race301.code &
PID1=$!

curl -s -o /tmp/race302.json -w "%{http_code}" \
  -X POST http://127.0.0.1:8000/api/reservations \
  -H "Content-Type: application/json" \
  -d '{"event_id":3,"user_id":302,"quantity":1}' \
  > /tmp/race302.code &
PID2=$!

wait $PID1
wait $PID2

echo "===== USUARIO 301 ====="
echo "HTTP $(cat /tmp/race301.code)"
cat /tmp/race301.json | python3 -m json.tool

echo "===== USUARIO 302 ====="
echo "HTTP $(cat /tmp/race302.code)"
cat /tmp/race302.json | python3 -m json.tool
```

Resultado verificado:

```text
Usuario 301  HTTP 200  CONFIRMED
Usuario 302  HTTP 409  sin asiento
```

El usuario ganador puede cambiar entre ejecuciones; lo obligatorio es tener **un ganador y un rechazo**.

### Verificar que no hubo sobreventa

```bash
kubectl exec -n ticket-system deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "SELECT event_id,available FROM inventory WHERE event_id=3; SELECT user_id,event_id,quantity,status FROM reservations WHERE event_id=3 AND user_id IN (301,302) ORDER BY created_at DESC;"
```

Resultado verificado:

```text
available = 0
una sola reserva CONFIRMED
nunca available = -1
```

**Defensa:** operación atómica condicionada en PostgreSQL.

---

# 🛡️ Prueba adicional — pérdida de un nodo

Esta prueba demuestra disponibilidad del sistema cuando se retiran los workloads de `Gabriel-node`.

## 1. Estado inicial

```bash
kubectl get nodes
kubectl get pods -n ticket-system -o wide
```

## 2. Drenar Gabriel

```bash
kubectl drain gabriel-node --ignore-daemonsets --delete-emptydir-data
```

Resultado esperado:

```text
node/gabriel-node drained
```

## 3. Ver estado durante el fallo

```bash
kubectl get nodes
kubectl get pods -n ticket-system -o wide
```

Se observa:

```text
gabriel-node   Ready,SchedulingDisabled
jordy-node     Ready
```

Las réplicas adicionales pueden aparecer `Pending` mientras solo exista un nodo schedulable. Las réplicas sobrevivientes y PostgreSQL continúan en `Jordy-node`.

## 4. Abrir el Gateway sobreviviente de Jordy

Obtener el pod:

```bash
kubectl get pods -n ticket-system -l app=api-gateway -o wide
```

Elegir el que esté en `jordy-node` y abrir:

```bash
kubectl port-forward pod/<POD_GATEWAY_JORDY> 8006:8000 \
  -n ticket-system --address 127.0.0.1
```

Comprobar:

```bash
curl -s http://127.0.0.1:8006/health | python3 -m json.tool
```

## 5. Reserva con Gabriel drenado

```bash
curl -s -X POST http://127.0.0.1:8006/api/reservations \
  -H "Content-Type: application/json" \
  -d '{"event_id":1,"user_id":9005,"quantity":1}' \
  | python3 -m json.tool
```

Resultado obtenido en la prueba final:

```text
Reservation    CONFIRMED
Inventory      RESERVED
Payment        APPROVED
Notification   SENT
```

Las instancias de Reservation, Inventory, Payment y Notification correspondieron a pods ejecutándose en `Jordy-node`.

## 6. Recuperar Gabriel

```bash
kubectl uncordon gabriel-node
sleep 10
kubectl get nodes
kubectl get pods -n ticket-system -o wide
```

Después se verificó una nueva reserva normal `CONFIRMED`.

> `drain` representa una retirada controlada del nodo de workloads. No equivale a un apagado eléctrico instantáneo del control-plane.

---

# 🗃️ Persistencia

Ver PVC y PV:

```bash
kubectl get pvc -n ticket-system -o wide
kubectl get pv -o wide
```

Inspeccionar el volumen:

```bash
kubectl describe pv <NOMBRE_PV>
```

En la ejecución final se verificó:

```text
StorageClass: local-path
AccessModes: RWO
Node Affinity: kubernetes.io/hostname in [jordy-node]
```

---

# 🧪 Imágenes Docker

```text
upsgabriel/ticket-api-gateway:1.0.0
upsgabriel/ticket-reservation-service:1.0.0
upsgabriel/ticket-inventory-service:1.0.0
upsgabriel/ticket-payment-service:1.0.0
upsgabriel/ticket-notification-service:1.0.0
postgres:16-alpine
```

Los scripts PowerShell de construcción/prueba siguen disponibles:

```powershell
docker login
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-images.ps1 -Action all
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-images.ps1 -Action all
```

---

# 💻 Entorno local alternativo

El repositorio conserva:

- `docker-compose.yml` para integración local.
- `kind-config.yaml` para un clúster KIND de desarrollo.
- scripts PowerShell en `scripts/` y `chaos/`.

Estos recursos son útiles para desarrollo y repetición local, pero **la evidencia final de la práctica se obtuvo en K3s sobre dos Droplets de DigitalOcean**.

---

# 📚 Documentación

- [Arquitectura final](docs/ARQUITECTURA.md)
- [Catálogo de fallos y defensas](docs/FALLOS.md)
- [Guion de demo de 10–15 minutos](docs/DEMO.md)
- [Checklist de evidencias](docs/EVIDENCIAS.md)
- [Análisis de los dos fallos teóricos](docs/ANALISIS-FALLOS.md)
- [Trabajo de Gabriel](docs/GABO.md)
- [Trabajo de Jordy](docs/JORDY.md)

---

# 🎯 Qué demuestra esta práctica

El objetivo no es simplemente mantener pods `Running`. La práctica demuestra que el sistema puede **degradarse de forma controlada y recuperarse**:

- si desaparece una réplica de Inventory, otra sigue atendiendo;
- si Payment tarda demasiado, la reserva queda persistida como `PAYMENT_PENDING`;
- si un cliente supera la tasa permitida, el Gateway protege el sistema con `429`;
- si dos usuarios compiten por un asiento, PostgreSQL impide la sobreventa;
- si se drena un nodo completo de aplicación, el nodo sobreviviente mantiene el flujo de reservas;
- cuando el nodo vuelve, Kubernetes restablece la capacidad del clúster.

Ese comportamiento fue validado con salidas de `kubectl`, respuestas HTTP, logs de pods y consultas directas a PostgreSQL.

# Parte GABO

## Responsabilidades principales

Gabriel implementó y validó principalmente:

- API Gateway (`api-gateway`).
- Reservation Service (`reservation-service`).
- Inventory Service (`inventory-service`).
- PostgreSQL e inicialización de datos.
- Docker Compose para integración local.
- manifiestos Kubernetes base.
- Inventario Fantasma.
- Diluvio de Peticiones.
- Condición de Carrera.
- prueba adicional de Base de Datos Intermitente.
- integración final del clúster K3s multinodo y pruebas de alta disponibilidad.

La infraestructura final no utiliza KIND para la evidencia: se desplegó en **DigitalOcean con K3s**, usando `gabriel-node` como server/control-plane y `jordy-node` como agent/worker.

## Arquitectura de la parte base

```text
Cliente
  |
  v
API Gateway :8000
  |
  v
Reservation Service :8001
  |
  +-------> Inventory Service :8002 -------> PostgreSQL :5432
  |
  +-------> Payment Service :8003
  |
  +-------> Notification Service :8004
  |
  +----------------------------------------> PostgreSQL :5432
```

## API Gateway

Funciones principales:

- punto de entrada de solicitudes;
- rate limiting: máximo 10 solicitudes por cliente en 10 segundos;
- bulkhead mediante semáforo para limitar concurrencia;
- timeout y manejo de indisponibilidad de Reservation Service.

## Reservation Service

Funciones principales:

- coordina Inventory, Payment y Notification;
- reintenta Inventory tres veces con backoff;
- aplica fallback si Payment o Notification no responden;
- persiste cada reserva en PostgreSQL;
- conserva reservas como `PAYMENT_PENDING` cuando Payment supera el timeout.

## Inventory Service

Funciones principales:

- consulta y descuenta asientos;
- utiliza actualización atómica condicionada por disponibilidad;
- evita inventario negativo y sobreventa;
- devuelve HTTP 409 cuando no existe stock suficiente.

## PostgreSQL

Tablas principales:

- `events`;
- `inventory`;
- `reservations`.

En K3s usa un PVC de 1 GiB con `StorageClass=local-path`. Durante la ejecución final el volumen quedó asociado a `jordy-node`.

## Imágenes Docker

```text
upsgabriel/ticket-api-gateway:1.0.0
upsgabriel/ticket-reservation-service:1.0.0
upsgabriel/ticket-inventory-service:1.0.0
```

Los scripts locales permanecen disponibles:

```powershell
docker login
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-images.ps1 -Action all
```

## Despliegue final en K3s

Desde `gabriel-node`:

```bash
cd ~/ticket-reservation-system
kubectl apply -f k8s/gabo/all.yaml
kubectl apply -f k8s/jordy/all.yaml

kubectl get nodes -o wide
kubectl get pods -n ticket-system -o wide
kubectl get services -n ticket-system
```

Resultado verificado:

```text
gabriel-node   Ready   control-plane
jordy-node     Ready
```

Los servicios HTTP se ejecutan con dos réplicas y, en condiciones normales, se distribuyen entre los dos hosts.

## Escenarios prácticos ejecutados

### Inventario Fantasma

Se eliminó deliberadamente la réplica de Inventory alojada en `gabriel-node`.

Resultado final:

```text
réplica eliminada        OK
otra réplica disponible  OK
reserva durante fallo    CONFIRMED
pod recreado              OK
```

Mecanismos:

- replicación;
- Kubernetes Service;
- retry con backoff;
- autorrecuperación del Deployment.

### Diluvio de Peticiones

Se enviaron 15 solicitudes rápidas contra una sola réplica del Gateway.

Resultado:

```text
Solicitudes 1–10   HTTP 404
Solicitudes 11–15  HTTP 429
Después de 11 s    HTTP 404
```

El endpoint de prueba no existe; el 404 permite atravesar el middleware sin crear reservas reales. El 429 demuestra la protección por rate limiting.

Mecanismos:

- rate limiting;
- bulkhead;
- rechazo controlado;
- recuperación automática de la ventana.

### Condición de Carrera

Se configuró el evento 3 con un solo asiento y se lanzaron dos reservas concurrentes.

Resultado observado:

```text
Usuario 301 -> HTTP 200 -> CONFIRMED
Usuario 302 -> HTTP 409
Inventario final -> 0
```

El ganador puede cambiar entre ejecuciones. La propiedad garantizada es que solo una reserva consume el último asiento.

Mecanismo:

- actualización SQL atómica condicionada;
- prevención de inventario negativo y sobreventa.

### Base de Datos Intermitente — prueba adicional

La prueba adicional de PostgreSQL permanece disponible como ejercicio de resiliencia, aunque el escenario oficial se mantiene dentro de los dos fallos teóricos.

El objetivo es comprobar errores controlados durante indisponibilidad de la base, restauración del servicio y persistencia de los datos anteriores.

## Alta disponibilidad de nodo

La infraestructura final también se probó retirando `gabriel-node` de la planificación:

```bash
kubectl drain gabriel-node --ignore-daemonsets --delete-emptydir-data
```

Durante el drain:

```text
gabriel-node   Ready,SchedulingDisabled
jordy-node     Ready
```

Se abrió un port-forward al Gateway sobreviviente en `jordy-node` y una reserva completa terminó:

```text
Reservation   CONFIRMED
Inventory     RESERVED
Payment       APPROVED
Notification  SENT
```

Después:

```bash
kubectl uncordon gabriel-node
```

Kubernetes recuperó capacidad y se verificó otra reserva `CONFIRMED`.

## Estado final de la parte GABO

```text
COMPLETO  API Gateway
COMPLETO  Reservation Service
COMPLETO  Inventory Service
COMPLETO  PostgreSQL y persistencia
COMPLETO  Docker e imágenes
COMPLETO  Kubernetes/K3s de dos nodos
COMPLETO  DNS interno
COMPLETO  Réplicas distribuidas
COMPLETO  Inventario Fantasma
COMPLETO  Condición de Carrera
COMPLETO  Diluvio de Peticiones
COMPLETO  prueba de drain y recuperación
ADICIONAL Base de Datos Intermitente
```

## Guion corto

> Mi parte implementa la ruta principal de reservas. El cliente entra por el API Gateway, donde aplicamos rate limiting y bulkhead. Reservation coordina Inventario, Pago y Notificación y persiste el resultado en PostgreSQL. Inventory realiza un descuento atómico para evitar vender dos veces el último asiento. En la infraestructura final usamos K3s sobre dos servidores DigitalOcean. Probamos la pérdida de una réplica sin interrupción, concurrencia por el último asiento, sobrecarga del Gateway y la retirada de un nodo completo de workloads mientras el segundo nodo mantuvo una reserva CONFIRMED.

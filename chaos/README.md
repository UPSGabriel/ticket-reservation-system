# Chaos scenarios

Este directorio contiene dos grupos de scripts:

- `k3s-*.sh`: **scripts finales de la práctica**, diseñados para Ubuntu + K3s en DigitalOcean.
- `*.ps1`: scripts conservados del entorno Windows/KIND utilizado durante desarrollo y pruebas locales.

Para la demo final se usan los scripts Bash de K3s.

## Requisitos

Ejecutar desde `gabriel-node` con:

- ambos nodos `Ready`;
- namespace `ticket-system` desplegado;
- `kubectl` funcionando;
- `curl` y `python3` disponibles;
- Payment y Notification desplegados;
- PostgreSQL disponible.

Comprobación inicial:

```bash
kubectl get nodes -o wide
kubectl get pods -n ticket-system -o wide
kubectl get services -n ticket-system
```

Para Inventario Fantasma, Pasarela Lenta y Condición de Carrera mantener un port-forward principal en otra terminal:

```bash
kubectl port-forward service/api-gateway 8000:8000 \
  -n ticket-system --address 127.0.0.1
```

Diluvio de Peticiones abre automáticamente su propio port-forward hacia una única réplica del Gateway.

---

## 1. Inventario Fantasma

```bash
bash chaos/k3s-inventario-fantasma.sh
```

Demuestra:

- eliminación de una réplica de Inventory en `gabriel-node`;
- continuidad de una reserva mediante la réplica sobreviviente;
- recreación automática del pod.

Variables opcionales:

```bash
TARGET_NODE=gabriel-node USER_ID=9102 bash chaos/k3s-inventario-fantasma.sh
```

---

## 2. Pasarela Lenta

```bash
bash chaos/k3s-pasarela-lenta.sh
```

Demuestra:

- reserva inicial `CONFIRMED`;
- `PAYMENT_DELAY_SECONDS=20`;
- timeout de Reservation a los 3 segundos;
- fallback `PAYMENT_PENDING`;
- persistencia en PostgreSQL;
- restauración de configuración;
- reserva final `CONFIRMED`.

El script guarda la configuración previa de Payment/Notification y la restaura incluso si el escenario falla.

---

## 3. Diluvio de Peticiones

```bash
bash chaos/k3s-diluvio-peticiones.sh
```

Demuestra:

- solicitudes 1–10 admitidas por el middleware y terminando en HTTP 404 por la ruta de prueba;
- solicitudes 11–15 rechazadas con HTTP 429;
- logs de rate limiting;
- recuperación automática de la ventana.

Se prueba una única réplica del Gateway para que las 15 solicitudes usen el mismo contador local.

---

## 4. Condición de Carrera

```bash
bash chaos/k3s-condicion-carrera.sh
```

Demuestra:

- evento con un único asiento;
- dos solicitudes concurrentes;
- exactamente un HTTP 200 y un HTTP 409;
- inventario final igual a 0;
- una única reserva `CONFIRMED` para los dos usuarios del experimento.

---

## Orden recomendado para la demo

```text
1. Inventario Fantasma
2. Pasarela Lenta
3. Diluvio de Peticiones
4. Condición de Carrera
```

Antes de Condición de Carrera el script espera 11 segundos para evitar que una ventana de rate limiting residual contamine el experimento.

## Comprobación de sintaxis sin ejecutar fallos

Después de actualizar el repositorio en `gabriel-node`:

```bash
bash -n chaos/k3s-inventario-fantasma.sh
bash -n chaos/k3s-pasarela-lenta.sh
bash -n chaos/k3s-diluvio-peticiones.sh
bash -n chaos/k3s-condicion-carrera.sh
```

Si los cuatro comandos terminan sin salida, Bash no detectó errores de sintaxis.

## Nota de seguridad operativa

No ejecutar los cuatro scripts simultáneamente. Cada escenario modifica temporalmente el estado del clúster o de los datos y está diseñado para ejecutarse de forma secuencial durante la demo.

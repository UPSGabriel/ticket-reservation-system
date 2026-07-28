# Evidencias de la práctica

Este archivo resume las evidencias obtenidas durante la ejecución final del clúster K3s en DigitalOcean.

## Convención sugerida de archivos

Guardar las capturas dentro de `docs/evidencias/` con nombres similares a:

```text
01_cluster_dos_nodos.png
02_distribucion_pods.png
03_servicios_kubernetes.png
04_dns_interno.png
05_reserva_normal_confirmed.png
06_inventario_fantasma_antes.png
07_inventario_fantasma_durante.png
08_inventario_fantasma_recuperado.png
09_pasarela_lenta_configuracion.png
10_pasarela_lenta_payment_pending.png
11_pasarela_lenta_timeout.png
12_pasarela_lenta_log_payment_20s.png
13_pasarela_lenta_postgres.png
14_pasarela_lenta_recuperacion.png
15_diluvio_http_429.png
16_diluvio_logs.png
17_diluvio_recuperacion.png
18_carrera_asiento_inicial.png
19_carrera_respuestas.png
20_carrera_inventario_cero.png
21_drain_antes.png
22_drain_ejecucion.png
23_drain_durante.png
24_gateway_jordy_vivo.png
25_reserva_durante_drain.png
26_uncordon_recuperacion.png
27_replicas_finales.png
28_reserva_final_confirmed.png
29_jordy_k3s_agent.png
30_jordy_contenedores.png
```

## Checklist final

| Evidencia | Comando o fuente | Estado final |
|---|---|---|
| Dos nodos `Ready` | `kubectl get nodes -o wide` | ✅ Verificado |
| Réplicas distribuidas | `kubectl get pods -n ticket-system -o wide` | ✅ Verificado |
| Services | `kubectl get services -n ticket-system` | ✅ Verificado |
| DNS interno | resolución desde Reservation Service | ✅ Verificado |
| Reserva normal | POST al Gateway | ✅ `CONFIRMED` |
| Inventario Fantasma | eliminación de una réplica de Inventory | ✅ Reserva siguió `CONFIRMED` y pod fue recreado |
| Pasarela Lenta | `PAYMENT_DELAY_SECONDS=20` | ✅ `PAYMENT_PENDING`, logs y persistencia |
| Diluvio | 15 solicitudes al mismo Gateway | ✅ 5 respuestas HTTP 429 |
| Condición de Carrera | dos solicitudes concurrentes | ✅ un 200, un 409, inventario 0 |
| Drain de nodo | `kubectl drain gabriel-node ...` | ✅ Servicio continuó en Jordy |
| Recuperación de nodo | `kubectl uncordon gabriel-node` | ✅ Réplicas recuperadas |
| Reserva final | POST después de recuperar | ✅ `CONFIRMED` |
| Worker Jordy | `systemctl status k3s-agent` | ✅ `active (running)` |
| Contenedores Jordy | `k3s crictl ps` | ✅ workloads visibles |

## Qué debe verse en cada fallo

Cada conjunto de evidencias debe incluir, cuando aplique:

1. Estado antes del fallo.
2. Comando que activa el fallo.
3. Respuesta o estado durante el fallo.
4. Logs que muestran la defensa.
5. Estado después de recuperar.

### Inventario Fantasma

Debe verse:

- dos réplicas antes;
- eliminación de la réplica de `gabriel-node`;
- reserva `CONFIRMED` atendida por la réplica sobreviviente;
- pod nuevo recreado por Kubernetes.

### Pasarela Lenta

Imprescindible mostrar:

- `PAYMENT_DELAY_SECONDS=20`;
- respuesta `PAYMENT_PENDING`;
- log de Reservation indicando indisponibilidad/timeout;
- log de Payment con `esperara 20.000 segundos`;
- fila PostgreSQL `PAYMENT_PENDING / PAYMENT_PENDING / NOT_SENT`;
- restauración a demora 0;
- nueva reserva `CONFIRMED`.

### Diluvio de Peticiones

Debe verse:

- Gateway seleccionado;
- solicitudes 1–10 antes del límite;
- solicitudes 11–15 en HTTP 429;
- logs `Solicitud rechazada por rate limiting`;
- después de 11 s, fin de la ventana y respuesta distinta de 429.

### Condición de Carrera

Debe verse:

- evento 3 con `available=1`;
- dos solicitudes concurrentes;
- un HTTP 200 y un HTTP 409;
- `available=0` al final;
- una única reserva confirmada para ese último asiento.

## Evidencia de alta disponibilidad de nodo

La prueba adicional se documenta con una secuencia clara:

### Antes

```bash
kubectl get nodes
kubectl get pods -n ticket-system -o wide
```

Ambos nodos `Ready` y réplicas distribuidas.

### Inyección

```bash
kubectl drain gabriel-node --ignore-daemonsets --delete-emptydir-data
```

Debe aparecer:

```text
node/gabriel-node drained
```

### Durante

```text
gabriel-node   Ready,SchedulingDisabled
jordy-node     Ready
```

Las réplicas sobrevivientes y PostgreSQL permanecen en `jordy-node`.

### Prueba funcional durante el drain

Se abre port-forward al Gateway que vive en `jordy-node` y se crea una reserva.

Resultado observado:

```text
Reservation   CONFIRMED
Inventory     RESERVED
Payment       APPROVED
Notification  SENT
```

### Recuperación

```bash
kubectl uncordon gabriel-node
```

Se comprueba nuevamente `kubectl get pods -o wide` y una reserva final `CONFIRMED`.

## Evidencia desde el worker

En `Jordy-node` se ejecutó:

```bash
hostname
systemctl status k3s-agent --no-pager
k3s crictl ps
```

Se verificó:

- hostname `Jordy-node`;
- `k3s-agent.service` en `active (running)`;
- contenedores de Reservation, Inventory, Payment, Notification, PostgreSQL y API Gateway ejecutándose en el worker.

## Nota de honestidad técnica

PostgreSQL usa un volumen `local-path` asociado a `jordy-node`. Por eso la prueba de nodo drena `gabriel-node` y no intenta afirmar tolerancia completa a la pérdida arbitraria de cualquiera de los dos nodos.

La evidencia demuestra disponibilidad de los microservicios ante pérdida de sus réplicas en un nodo y continuidad completa del flujo mientras el nodo que conserva PostgreSQL permanece disponible.

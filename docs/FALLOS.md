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
| Inventario Fantasma | Disponibilidad | Eliminar un pod de Inventory con `kubectl delete pod` | Dos réplicas, distribución entre nodos, retry con backoff y autorrecuperación de Kubernetes | Pod eliminado, segunda réplica atendiendo y pod recreado |
| Pasarela Lenta | Latencia | `PAYMENT_DELAY_SECONDS=20` mediante `kubectl set env` | Timeout de 3 s y fallback `PAYMENT_PENDING` | HTTP 200 controlado, logs del timeout y fila persistida |
| Diluvio de Peticiones | Sobrecarga | Script con 15 solicitudes al Gateway | Rate limiting por ventana y bulkhead de concurrencia | Respuestas aceptadas, HTTP 429 y recuperación de ventana |
| Base de Datos Intermitente | Conectividad | Escalar PostgreSQL temporalmente a cero; en producción se usaría pérdida de red | Error 5xx controlado; propuesta: HA, retry seguro, circuit breaker e idempotencia | Explicación teórica y diseño de producción |
| Correo Perdido | Fallo no crítico | `NOTIFICATION_FAILURE_MODE=drop` o caída del servicio | Fallback `NOTIFICATION_PENDING`; propuesta: Transactional Outbox, cola, retries y DLQ | Explicación teórica y reserva conservada |
| Condición de Carrera | Consistencia | Dos solicitudes concurrentes para el último asiento | Descuento atómico condicionado en PostgreSQL | Un HTTP 200, un HTTP 409 e inventario nunca negativo |

## Justificación de los cuatro mecanismos prácticos

### Inventario Fantasma

Las réplicas solucionan disponibilidad, mientras el retry con backoff absorbe fallos transitorios durante la eliminación y recreación del pod. Un fallback que confirmara la compra sin consultar inventario sería incorrecto porque podría producir sobreventa.

Script:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-inventario-fantasma.ps1
```

### Pasarela Lenta

El timeout evita que Reservation Service mantenga conexiones bloqueadas durante los 20 segundos de Payment. El fallback conserva la reserva como `PAYMENT_PENDING`, permitiendo reanudar el pago posteriormente. No se reintenta inmediatamente porque podría producir cobros duplicados sin una clave de idempotencia.

Script:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\jordy-pasarela-lenta.ps1
```

### Diluvio de Peticiones

Rate limiting limita solicitudes por cliente/ventana. El bulkhead limita simultaneidad interna y evita que todas las solicitudes ocupen los recursos del Gateway. Escalar réplicas ayuda, pero no sustituye el control de admisión ante carga ilimitada.

Script:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-diluvio-peticiones.ps1
```

### Condición de Carrera

La operación atómica en PostgreSQL combina verificación y descuento en una única sentencia condicionada. Un retry no resolvería la carrera y podría empeorarla. La base de datos actúa como árbitro consistente: solamente una transacción puede descontar el último asiento.

Script:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-condicion-carrera.ps1
```

## Relación con la demo

Cada script debe mostrar el estado anterior, activar el fallo, capturar la respuesta y verificar recuperación o manejo controlado. Las capturas requeridas se enumeran en `docs/EVIDENCIAS.md`.

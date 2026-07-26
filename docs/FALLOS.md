# Cat?logo de los seis fallos

## Selecci?n

Los cuatro fallos pr?cticos oficiales son:

1. Inventario Fantasma.
2. Pasarela Lenta.
3. Diluvio de Peticiones.
4. Condici?n de Carrera.

Los dos fallos reservados para an?lisis y dise?o son Base de Datos Intermitente y Correo Perdido. La prueba adicional de base de datos no cambia esta selecci?n.

## Mapeo de inyecci?n y defensa

| Fallo | Tipo | Inyecci?n controlada | Defensa implementada o propuesta | Evidencia principal |
|---|---|---|---|---|
| Inventario Fantasma | Disponibilidad | Eliminar un pod de Inventory con `kubectl delete pod` | Dos r?plicas, distribuci?n entre nodos, retry con backoff y autorrecuperaci?n de Kubernetes | Pod eliminado, segunda r?plica atendiendo y pod recreado |
| Pasarela Lenta | Latencia | `PAYMENT_DELAY_SECONDS=20` mediante `kubectl set env` | Timeout de 3 s y fallback `PAYMENT_PENDING` | HTTP 200 controlado, logs del timeout y fila persistida |
| Diluvio de Peticiones | Sobrecarga | Script con 15 solicitudes al Gateway | Rate limiting por ventana y bulkhead de concurrencia | Respuestas aceptadas, HTTP 429 y recuperaci?n de ventana |
| Base de Datos Intermitente | Conectividad | Escalar PostgreSQL temporalmente a cero; en producci?n se usar?a p?rdida de red | Error 5xx controlado; propuesta: HA, retry seguro, circuit breaker e idempotencia | Explicaci?n te?rica y dise?o de producci?n |
| Correo Perdido | Fallo no cr?tico | `NOTIFICATION_FAILURE_MODE=drop` o ca?da del servicio | Fallback `NOTIFICATION_PENDING`; propuesta: Transactional Outbox, cola, retries y DLQ | Explicaci?n te?rica y reserva conservada |
| Condici?n de Carrera | Consistencia | Dos solicitudes concurrentes para el ?ltimo asiento | Descuento at?mico condicionado en PostgreSQL | Un HTTP 200, un HTTP 409 e inventario nunca negativo |

## Justificaci?n de los cuatro mecanismos pr?cticos

### Inventario Fantasma

Las r?plicas solucionan disponibilidad, mientras el retry con backoff absorbe fallos transitorios durante la eliminaci?n y recreaci?n del pod. Un fallback que confirmara la compra sin consultar inventario ser?a incorrecto porque podr?a producir sobreventa.

Script:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-inventario-fantasma.ps1
```

### Pasarela Lenta

El timeout evita que Reservation Service mantenga conexiones bloqueadas durante los 20 segundos de Payment. El fallback conserva la reserva como `PAYMENT_PENDING`, permitiendo reanudar el pago posteriormente. No se reintenta inmediatamente porque podr?a producir cobros duplicados sin una clave de idempotencia.

Script:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\jordy-pasarela-lenta.ps1
```

### Diluvio de Peticiones

Rate limiting limita solicitudes por cliente/ventana. El bulkhead limita simultaneidad interna y evita que todas las solicitudes ocupen los recursos del Gateway. Escalar r?plicas ayuda, pero no sustituye el control de admisi?n ante carga ilimitada.

Script:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-diluvio-peticiones.ps1
```

### Condici?n de Carrera

La operaci?n at?mica en PostgreSQL combina verificaci?n y descuento en una ?nica sentencia condicionada. Un retry no resolver?a la carrera y podr?a empeorarla. La base de datos act?a como ?rbitro consistente: solamente una transacci?n puede descontar el ?ltimo asiento.

Script:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-condicion-carrera.ps1
```

## Relaci?n con la demo

Cada script debe mostrar el estado anterior, activar el fallo, capturar la respuesta y verificar recuperaci?n o manejo controlado. Las capturas requeridas se enumeran en `docs/EVIDENCIAS.md`.

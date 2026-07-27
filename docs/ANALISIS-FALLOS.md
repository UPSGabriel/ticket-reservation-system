# Análisis y diseño de los dos fallos restantes

Este documento es la fuente del informe PDF final. Antes de entregar, debe incorporar las referencias exactas utilizadas por la pareja en su investigación MLR.

## 1. Base de Datos Intermitente

### Por qué ocurre

Una pérdida intermitente de conectividad crea particiones breves entre Reservation/Inventory y PostgreSQL. El cliente puede observar timeout sin saber si la transacción nunca llegó, fue abortada o se confirmó y se perdió solamente la respuesta. Reintentar ciegamente una escritura puede duplicar la operación.

En términos de CAP, durante una partición un sistema que mantiene una única autoridad consistente para inventario prefiere rechazar temporalmente operaciones antes que aceptar dos ventas incompatibles. La disponibilidad de escritura disminuye para preservar consistencia.

### Solución de producción

- PostgreSQL de alta disponibilidad con réplica síncrona y failover administrado.
- Timeouts cortos y pool de conexiones con límites.
- Retry exponencial con jitter únicamente para errores transitorios.
- Circuit Breaker para evitar presión continua sobre una base degradada.
- Claves de idempotencia para que repetir una solicitud no duplique reservas.
- Métricas de conexiones, latencia, errores y failover.
- Backups y pruebas periódicas de restauración.

### Pseudocódigo

```text
crearReserva(comando, claveIdempotencia):
    existente = buscarPorClave(claveIdempotencia)
    si existente:
        retornar existente

    si circuitBreakerDB.estaAbierto():
        retornar ERROR_TEMPORAL

    para intento en 1..3:
        intentar:
            iniciar transaccion
            descontar inventario atomicamente
            guardar reserva con clave unica
            confirmar transaccion
            circuitBreakerDB.registrarExito()
            retornar CONFIRMED
        capturar errorTransitorio:
            deshacer transaccion
            esperar backoffConJitter(intento)

    circuitBreakerDB.registrarFallo()
    retornar ERROR_CONTROLADO
```

### Relación con el prototipo

`chaos/gabo-base-datos-intermitente.ps1` apaga PostgreSQL, comprueba un error 5xx controlado y restaura el Deployment. Es una aproximación de laboratorio; una prueba de red con Toxiproxy o NetworkPolicy representaría mejor el flapping real.

## 2. Correo Perdido

### Por qué ocurre

Notification es una dependencia no crítica: la reserva y el pago pueden completarse aunque el correo falle. Si Reservation guarda la compra y luego llama directamente al correo, existe un problema de doble escritura: el proceso puede caer entre la confirmación en PostgreSQL y el envío, dejando una reserva válida sin notificación.

Exigir que el correo participe en la misma transacción haría que una dependencia secundaria reduzca la disponibilidad del flujo principal. La solución debe aceptar consistencia eventual para la notificación.

### Solución de producción: Transactional Outbox

Reservation guarda la reserva y un evento `ReservationConfirmed` dentro de la misma transacción PostgreSQL. Un publicador independiente lee la tabla outbox y envía el evento a una cola. Notification consume el mensaje de forma idempotente, reintenta con backoff y mueve fallos permanentes a una Dead Letter Queue.

```mermaid
flowchart LR
    R[Reservation Service] -->|misma transacción| DB[(reservations + outbox)]
    DB --> P[Outbox Publisher]
    P --> Q[(Message Broker)]
    Q --> N[Notification Worker]
    N --> M[Proveedor de correo]
    N -->|fallo permanente| D[(Dead Letter Queue)]
```

### Pseudocódigo

```text
confirmarReserva(datos):
    iniciar transaccion
    guardar reserva CONFIRMED
    guardar outbox(eventId unico, tipo ReservationConfirmed, payload)
    confirmar transaccion
    retornar CONFIRMED

publicarOutbox():
    para evento pendiente:
        publicarEnCola(evento)
        marcarPublicado(evento.id)

consumirNotificacion(evento):
    si evento.id ya fue procesado:
        confirmar mensaje
        retornar

    intentar enviar correo con backoff
    si exito:
        guardar evento.id como procesado
        confirmar mensaje
    si supera maximo de intentos:
        mover a DLQ
```

### Relación con el prototipo

`NOTIFICATION_FAILURE_MODE=drop` devuelve HTTP 503. Reservation conserva el pago y persiste `NOTIFICATION_PENDING`. Esto demuestra el fallback, mientras Outbox + cola representa la evolución adecuada para producción.

## Comparación

| Aspecto | Base intermitente | Correo perdido |
|---|---|---|
| Criticidad | Alta: inventario y reservas | Secundaria |
| Consistencia | Fuerte para impedir duplicados/sobreventa | Eventual |
| Respuesta inmediata | Error controlado si no se puede persistir | Reserva válida con notificación pendiente |
| Defensa principal | HA, idempotencia, retry seguro y circuit breaker | Outbox, cola, consumidor idempotente y DLQ |

## Pendiente editorial para el PDF

- Añadir portada, integrantes y fecha.
- Incorporar citas de la investigación MLR de la pareja.
- Exportar este contenido a PDF.
- Revisar que los diagramas se rendericen correctamente.

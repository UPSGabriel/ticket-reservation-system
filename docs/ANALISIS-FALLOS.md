# Análisis y diseño de los dos fallos restantes

Este documento desarrolla los dos escenarios que no forman parte de los cuatro experimentos oficiales: **Base de Datos Intermitente** y **Correo Perdido**. El análisis conecta cada fallo con fundamentos de sistemas distribuidos y propone una solución de nivel producción.

La MLR previa de la pareja estudió **algoritmos de consenso y quorum mediante Raft**, con énfasis en fallos por parada y particiones de red, pérdida de quorum, replicación consistente y evidencia industrial en etcd/Kubernetes y CockroachDB. Esa investigación sirve especialmente como respaldo conceptual para el análisis de una base de datos distribuida o replicada sometida a particiones.

---

# 1. Base de Datos Intermitente

## 1.1 Por qué ocurre

El fallo representa una conectividad que aparece y desaparece entre Reservation/Inventory y PostgreSQL. No es equivalente a que la base permanezca apagada: durante el *flapping* algunas operaciones pueden alcanzar el servidor y otras no.

Esto crea una dificultad importante para las escrituras. Un cliente puede observar un timeout sin saber si:

1. la operación nunca llegó al servidor;
2. llegó pero fue abortada;
3. fue confirmada y únicamente se perdió la respuesta.

Por ello, reintentar escrituras de manera ciega puede duplicar una operación.

Desde la perspectiva de CAP, cuando existe una partición de red un sistema distribuido debe decidir qué propiedad sacrifica temporalmente entre disponibilidad y consistencia. Para inventario de entradas, aceptar dos escrituras incompatibles sería peor que rechazar temporalmente una reserva; por eso la estrategia prioriza una autoridad consistente para impedir sobreventa.

## 1.2 Relación con la MLR de Raft/quorum

La MLR previa analizó que los sistemas basados en Raft avanzan mientras conservan un quorum capaz de llegar a consenso. Cuando una partición elimina la mayoría necesaria, el sistema puede detener nuevas escrituras para preservar consistencia en lugar de producir estados divergentes.

La conexión con este escenario no implica que el PostgreSQL del prototipo use Raft. El aprendizaje transferido es el **trade-off entre continuidad de escritura y consistencia durante una partición**, además de la importancia de replicación, quorum, recuperación y observabilidad en sistemas reales.

## 1.3 Inyección representativa

Para representar conectividad intermitente de forma más fiel en un entorno Kubernetes de producción/laboratorio se utilizaría uno de estos mecanismos:

- una `NetworkPolicy` que bloquee temporalmente el tráfico hacia PostgreSQL y luego se retire;
- Toxiproxy u otro proxy de fallos que alterne pérdida de conexión, latencia o resets TCP.

La prueba adicional existente que escala PostgreSQL a cero representa **indisponibilidad total** y se conserva como evidencia complementaria, pero no se presenta como simulación exacta de flapping.

## 1.4 Solución de producción

Una solución robusta combinaría:

- PostgreSQL de alta disponibilidad con réplicas y failover administrado;
- almacenamiento replicado o gestionado, no un volumen local atado a un único nodo;
- timeouts cortos y límites en el pool de conexiones;
- retry exponencial con jitter exclusivamente para errores transitorios;
- Circuit Breaker para dejar de presionar una dependencia degradada;
- claves de idempotencia para que repetir una solicitud no duplique reservas;
- restricciones de integridad y transacciones para preservar consistencia;
- métricas de conexiones, timeouts, latencia, errores y failover;
- backups y pruebas periódicas de restauración.

## 1.5 Pseudocódigo

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

## 1.6 Propiedad buscada

La defensa no pretende que toda escritura sea aceptada durante una partición. Pretende que una pérdida de conectividad no genere datos ambiguos, duplicados ni sobreventa y que, cuando la infraestructura recupere conectividad, el sistema pueda continuar de forma segura.

---

# 2. Correo Perdido

## 2.1 Por qué ocurre

Notification es una dependencia no crítica para la validez de la compra. La reserva y el pago pueden completarse correctamente aunque el proveedor de correo esté caído.

El problema aparece cuando Reservation persiste la compra y después llama directamente a Notification. Existen dos efectos diferentes:

1. guardar el estado de negocio;
2. producir un efecto externo, el correo.

No existe una transacción ACID única que abarque PostgreSQL y un proveedor de correo. El proceso puede fallar después de confirmar la reserva pero antes de enviar el mensaje, dejando una compra válida sin notificación.

Hacer que toda la compra falle únicamente porque el correo no está disponible reduciría innecesariamente la disponibilidad del flujo principal.

## 2.2 Comportamiento del prototipo

El prototipo ya trata Notification como dependencia secundaria. Cuando el servicio no responde, Reservation aplica fallback y conserva el flujo como `NOTIFICATION_PENDING` en lugar de perder la reserva.

El stub permite forzar el fallo mediante:

```bash
kubectl set env deployment/notification-service -n ticket-system \
  NOTIFICATION_FAILURE_MODE=drop \
  NOTIFICATION_FAILURE_RATE=0
```

Este mecanismo es útil para laboratorio, pero una solución de producción debe evitar depender de una llamada síncrona para garantizar la notificación.

## 2.3 Solución de producción: Transactional Outbox

La propuesta es utilizar **Transactional Outbox**:

1. Reservation guarda la reserva y un evento `ReservationConfirmed` dentro de la misma transacción PostgreSQL.
2. Si la transacción confirma, ambos registros existen; si hace rollback, ninguno existe.
3. Un proceso publicador lee los eventos pendientes de la tabla outbox.
4. Publica cada evento en un broker de mensajes.
5. Notification consume el evento de manera idempotente.
6. Los errores transitorios se reintentan con backoff.
7. Los errores permanentes terminan en una Dead Letter Queue para inspección o reproceso.

```mermaid
flowchart LR
    R[Reservation Service] -->|misma transacción| DB[(reservations + outbox)]
    DB --> P[Outbox Publisher]
    P --> Q[(Message Broker)]
    Q --> N[Notification Worker]
    N --> M[Proveedor de correo]
    N -->|fallo permanente| D[(Dead Letter Queue)]
```

## 2.4 Pseudocódigo

```text
confirmarReserva(datos):
    iniciar transaccion
    guardar reserva CONFIRMED
    guardar outbox(
        eventId unico,
        tipo ReservationConfirmed,
        payload
    )
    confirmar transaccion
    retornar CONFIRMED

publicarOutbox():
    para evento pendiente:
        intentar publicarEnCola(evento)
        si publicacion confirmada:
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

## 2.5 Propiedad buscada

La reserva no depende de la disponibilidad instantánea del correo. El sistema acepta **consistencia eventual** para Notification: una notificación puede enviarse segundos o minutos después, pero el evento que representa la obligación de enviarla no se pierde.

---

# 3. Comparación de los dos fallos

| Aspecto | Base de Datos Intermitente | Correo Perdido |
|---|---|---|
| Criticidad | Alta: inventario y reservas | Secundaria |
| Problema distribuido | Partición, timeout y resultado incierto de una escritura | Doble escritura y dependencia externa |
| Consistencia | Fuerte para impedir duplicados/sobreventa | Eventual para la notificación |
| Respuesta inmediata | Error temporal controlado si no es seguro persistir | Reserva válida con notificación pendiente |
| Defensa principal | HA, idempotencia, retry seguro, circuit breaker | Outbox, broker, consumidor idempotente, retries, DLQ |
| Relación con MLR de Raft | Directa a nivel conceptual: particiones, quorum y consistencia | Indirecta; el mecanismo principal es mensajería confiable |

---

# 4. Relación con la Parte II

Estos dos escenarios permanecen en el catálogo de seis fallos, pero no sustituyen a los cuatro experimentos ejecutados en vivo. La separación final es:

```text
PRÁCTICOS
- Inventario Fantasma
- Pasarela Lenta
- Diluvio de Peticiones
- Condición de Carrera

ANÁLISIS Y DISEÑO
- Base de Datos Intermitente
- Correo Perdido
```

---

# 5. Referencias conectadas con la MLR previa

La MLR de la pareja seleccionó Raft como mecanismo de consenso/quorum y utilizó como fuentes preliminares de verificación, entre otras:

- Ongaro, D., & Ousterhout, J. (2014). *In Search of an Understandable Consensus Algorithm*. Proceedings of the 2014 USENIX Annual Technical Conference.
- The etcd Authors. (2021). *Frequently asked questions (FAQ)*. etcd Documentation.
- Kubernetes. (s. f.). *Operating etcd clusters for Kubernetes*. Kubernetes Documentation.
- Cockroach Labs. (s. f.). *Architecture Overview*. CockroachDB Documentation.

Estas referencias respaldan la discusión conceptual sobre consenso, quorum, consistencia, particiones y operación de sistemas distribuidos. La solución de Correo Perdido se fundamenta en patrones de mensajería confiable y consistencia eventual, no en Raft directamente.

---

## Estado del documento

Análisis técnico finalizado: ambos fallos incluyen causa específica, relación con fundamentos distribuidos, solución de producción y pseudocódigo o diagrama. El PDF de entrega debe conservar la misma selección de fallos y la bibliografía validada de la MLR.

# Parte GABO

## Contenido

- API Gateway (`api-gateway`)
- Reservation Service (`reservation-service`)
- Inventory Service (`inventory-service`)
- PostgreSQL (`database/init.sql`)
- Integración con Docker Compose (`docker-compose.yml`)
- Pruebas y evidencias de la ruta principal

## Arquitectura

```text
Cliente
  |
  v
API Gateway :8000
  |
  v
Reservation Service :8001
  |
  v
Inventory Service :8002
  |
  v
PostgreSQL :5432
```

## Qué hace cada componente

### API Gateway

- Recibe las solicitudes de reserva.
- Aplica rate limiting.
- Aplica bulkhead con un semáforo.
- Maneja timeouts y caídas del servicio principal.
- Endpoint principal: `POST /api/reservations`.

### Reservation Service

- Coordina inventario, pago y notificación.
- Reintenta Inventario tres veces con backoff exponencial.
- Aplica fallback cuando Pago o Notificación no están disponibles.
- Guarda las reservas en PostgreSQL.
- Permite listar y consultar reservas.

### Inventory Service

- Consulta la disponibilidad de eventos.
- Descuenta asientos de forma atómica en PostgreSQL.
- Evita inventario negativo.
- Devuelve `409 Conflict` cuando no hay suficientes asientos.
- Conserva los datos aunque el contenedor se reinicie.

### PostgreSQL

Tablas:

- `events`
- `inventory`
- `reservations`

El volumen `ticket_postgres_data` mantiene los datos entre reinicios.

## Ejecutar la demo

Desde la raíz del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabriel-demo.ps1
```

El script:

1. Detiene servidores Python viejos en los puertos 8000, 8001 y 8002.
2. Construye y levanta los contenedores.
3. Comprueba los endpoints de salud.
4. Reinicia el inventario de demostración.
5. Crea una reserva desde el API Gateway.
6. Comprueba que el inventario disminuyó.
7. Consulta la reserva guardada.
8. Muestra las filas de PostgreSQL.

## Pruebas para la exposición

### Estado de los contenedores

```powershell
docker compose ps
```

Deben aparecer:

- `ticket-postgres`
- `ticket-inventory`
- `ticket-reservation`
- `ticket-gateway`

### Reserva normal

Abrir `http://localhost:8000/docs` y ejecutar `POST /api/reservations`:

```json
{
  "event_id": 1,
  "user_id": 101,
  "quantity": 2
}
```

Mientras Pago no esté listo, el estado esperado es `PAYMENT_PENDING`. La reserva queda guardada y el inventario disminuye.

### Inventario insuficiente

Usar el evento 3, que tiene un solo asiento:

```json
{
  "event_id": 3,
  "user_id": 102,
  "quantity": 2
}
```

Resultado esperado: `409 Conflict`.

### Persistencia

```powershell
docker compose restart inventory-service reservation-service
curl.exe http://localhost:8002/inventory/1
```

El valor debe mantenerse porque está guardado en PostgreSQL.

### Caída de Inventario

```powershell
docker compose stop inventory-service
```

Crear una reserva desde el Gateway. Reservation Service hará tres intentos y devolverá `503`.

Restaurar:

```powershell
docker compose start inventory-service
```

### Rate limiting

Enviar más de diez solicitudes en diez segundos al Gateway. El exceso debe devolver `429 Too Many Requests`.

## Guion corto

> Mi parte implementa la ruta principal de reservas. El cliente entra por el API Gateway, donde usamos rate limiting y bulkhead para proteger el sistema. El Gateway llama al Reservation Service, que coordina el proceso. Este servicio intenta reservar inventario con reintentos y backoff, aplica fallback si Pago o Notificación fallan y guarda el resultado en PostgreSQL. El Inventory Service descuenta los asientos de forma atómica para evitar vender dos veces el último asiento. Docker Compose levanta e interconecta todos los componentes y PostgreSQL conserva la información aunque reiniciemos los contenedores.

## Capturas recomendadas

1. `docker compose ps` con los cuatro contenedores.
2. Los tres endpoints `/health`.
3. Reserva creada desde Gateway.
4. Inventario antes y después.
5. Consulta SQL de `reservations`.
6. Error `409` por inventario insuficiente.
7. Error `503` al detener Inventario.
8. Recuperación al volver a iniciarlo.

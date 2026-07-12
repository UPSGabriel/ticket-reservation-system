# Parte de Gabriel Córdova

## Responsabilidad asignada

La parte de Gabriel comprende la ruta principal de una reserva y su persistencia:

1. **API Gateway** (`api-gateway`)
2. **Reservation Service** (`reservation-service`)
3. **Inventory Service** (`inventory-service`)
4. **PostgreSQL** (`database/init.sql`)
5. **Integración local con Docker Compose** (`docker-compose.yml`)
6. **Pruebas y evidencias de la ruta completa**

La parte pendiente para Jordy corresponde a Payment Service, Notification Service, despliegue Kubernetes multinodo y escenarios de caos finales.

## Arquitectura de la parte de Gabriel

```text
Cliente
  |
  v
API Gateway :8000
  |
  v
Reservation Service :8001
  |                 \
  v                  \ fallback
Inventory Service     Payment/Notification
:8002                 (parte de Jordy)
  |
  v
PostgreSQL :5432
```

## Qué implementa cada componente

### API Gateway

- Es el único punto de entrada para crear reservas.
- Aplica **rate limiting** por dirección IP.
- Aplica el patrón **bulkhead** mediante un semáforo.
- Maneja errores de timeout y caída del servicio principal.
- Endpoint principal: `POST /api/reservations`.

### Reservation Service

- Coordina la reserva de inventario, pago y notificación.
- Reintenta la comunicación con Inventario tres veces usando backoff exponencial.
- Aplica fallback cuando Pago o Notificación no están disponibles.
- Persiste la reserva en PostgreSQL.
- Permite listar y consultar reservas.

### Inventory Service

- Consulta la disponibilidad de eventos.
- Descuenta asientos con una actualización atómica en PostgreSQL.
- Evita inventario negativo y devuelve `409 Conflict` cuando no existen asientos suficientes.
- Conserva los datos aunque el contenedor sea reiniciado.

### PostgreSQL

Tablas creadas:

- `events`
- `inventory`
- `reservations`

El volumen `ticket_postgres_data` conserva los datos entre reinicios.

## Ejecución automática

Desde la raíz del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabriel-demo.ps1
```

El guion:

1. Detiene servidores Python viejos en los puertos 8000, 8001 y 8002.
2. Construye y levanta los contenedores.
3. Comprueba los tres endpoints de salud.
4. Reinicia el inventario de demostración.
5. Crea una reserva a través del API Gateway.
6. Comprueba que el inventario disminuyó.
7. Consulta la reserva persistida.
8. Muestra las filas guardadas directamente en PostgreSQL.

## Pruebas manuales para la exposición

### 1. Estado de los contenedores

```powershell
docker compose ps
```

Deben aparecer saludables o activos:

- `ticket-postgres`
- `ticket-inventory`
- `ticket-reservation`
- `ticket-gateway`

### 2. Reserva normal

Abrir `http://localhost:8000/docs` y ejecutar `POST /api/reservations`:

```json
{
  "event_id": 1,
  "user_id": 101,
  "quantity": 2
}
```

Mientras Pago no esté implementado, el estado correcto es `PAYMENT_PENDING`. La reserva sí queda persistida y el inventario sí disminuye.

### 3. Inventario insuficiente

Usar el evento 3, que tiene un solo asiento:

```json
{
  "event_id": 3,
  "user_id": 102,
  "quantity": 2
}
```

Resultado esperado: `409 Conflict`.

### 4. Persistencia

Consultar el inventario, reiniciar los contenedores y volver a consultar:

```powershell
docker compose restart inventory-service reservation-service
curl.exe http://localhost:8002/inventory/1
```

El valor debe mantenerse porque está almacenado en PostgreSQL.

### 5. Caída de Inventario y reintentos

```powershell
docker compose stop inventory-service
```

Crear una reserva desde el Gateway. Reservation Service realizará tres intentos y devolverá `503` sin confirmar la reserva.

Restaurar:

```powershell
docker compose start inventory-service
```

### 6. Rate limiting

Ejecutar más de diez solicitudes en diez segundos contra un endpoint protegido del Gateway. El exceso devuelve `429 Too Many Requests`.

## Guion corto para defender la parte

> Mi parte implementa la ruta principal de reservas. El cliente entra por el API Gateway, donde aplicamos rate limiting y bulkhead para proteger el sistema. El Gateway llama al Reservation Service, que funciona como orquestador. Este servicio intenta reservar inventario con reintentos y backoff, aplica fallback si Pago o Notificación no responden y guarda el resultado en PostgreSQL. El Inventory Service realiza un descuento atómico para impedir que dos solicitudes compren el mismo último asiento. Finalmente, Docker Compose levanta e interconecta todos estos componentes y PostgreSQL mantiene la información aunque reiniciemos los contenedores.

## Evidencias recomendadas

Guardar capturas de:

1. `docker compose ps` con cuatro contenedores.
2. Los tres endpoints `/health`.
3. Reserva creada desde Gateway.
4. Inventario antes y después de la reserva.
5. Consulta SQL de la tabla `reservations`.
6. Error `409` por inventario insuficiente.
7. Error `503` al detener Inventory Service.
8. Recuperación después de volver a iniciar Inventory Service.

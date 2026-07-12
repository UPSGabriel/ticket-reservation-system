import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, status
from psycopg.rows import dict_row
from pydantic import BaseModel, Field


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("reservation-service")

INVENTORY_SERVICE_URL = os.getenv(
    "INVENTORY_SERVICE_URL",
    "http://127.0.0.1:8002",
)
PAYMENT_SERVICE_URL = os.getenv(
    "PAYMENT_SERVICE_URL",
    "http://127.0.0.1:8003",
)
NOTIFICATION_SERVICE_URL = os.getenv(
    "NOTIFICATION_SERVICE_URL",
    "http://127.0.0.1:8004",
)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ticket_user:ticket_pass@127.0.0.1:5432/ticket_db",
)
INSTANCE_NAME = os.getenv("INSTANCE_NAME", "reservation-local")

app = FastAPI(
    title="Reservation Service",
    description="Servicio principal encargado de coordinar y persistir reservas.",
    version="1.1.0",
)


class ReservationRequest(BaseModel):
    event_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=10)


def open_connection() -> psycopg.Connection:
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=5,
        row_factory=dict_row,
        sslmode="disable",
    )


def serialize_row(row: dict) -> dict:
    result = dict(row)

    if isinstance(result.get("id"), UUID):
        result["id"] = str(result["id"])

    if isinstance(result.get("created_at"), datetime):
        result["created_at"] = result["created_at"].isoformat()

    return result


def check_database() -> int:
    with open_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS result;")
            row = cursor.fetchone()

    return row["result"] if row else 0


def save_reservation(
    reservation_id: str,
    payload: ReservationRequest,
    final_status: str,
    payment_status: str,
    notification_status: str,
) -> None:
    with open_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO reservations (
                    id,
                    event_id,
                    user_id,
                    quantity,
                    status,
                    payment_status,
                    notification_status,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
                """,
                (
                    reservation_id,
                    payload.event_id,
                    payload.user_id,
                    payload.quantity,
                    final_status,
                    payment_status,
                    notification_status,
                ),
            )
            connection.commit()


def read_reservation(reservation_id: str) -> dict | None:
    with open_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    event_id,
                    user_id,
                    quantity,
                    status,
                    payment_status,
                    notification_status,
                    created_at
                FROM reservations
                WHERE id = %s;
                """,
                (reservation_id,),
            )
            row = cursor.fetchone()

    return serialize_row(row) if row else None


def read_reservations() -> list[dict]:
    with open_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    event_id,
                    user_id,
                    quantity,
                    status,
                    payment_status,
                    notification_status,
                    created_at
                FROM reservations
                ORDER BY created_at DESC
                LIMIT 100;
                """
            )
            rows = cursor.fetchall()

    return [serialize_row(row) for row in rows]


async def reserve_inventory(payload: ReservationRequest) -> dict:
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "Intento %s de %s para contactar Inventario.",
                attempt,
                max_attempts,
            )

            async with httpx.AsyncClient(timeout=2.5) as client:
                response = await client.post(
                    f"{INVENTORY_SERVICE_URL}/inventory/reserve",
                    json={
                        "event_id": payload.event_id,
                        "quantity": payload.quantity,
                    },
                )

            if response.status_code == status.HTTP_200_OK:
                return response.json()

            if response.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="El evento solicitado no existe.",
                )

            if response.status_code == status.HTTP_409_CONFLICT:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No existen suficientes asientos disponibles.",
                )

            logger.warning(
                "Inventario respondió con código %s en el intento %s.",
                response.status_code,
                attempt,
            )

        except HTTPException:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning(
                "Inventario no respondió en el intento %s: %s",
                attempt,
                exc,
            )

        if attempt < max_attempts:
            wait_seconds = 0.5 * (2 ** (attempt - 1))
            logger.info(
                "Aplicando retry con backoff de %.1f segundos.",
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "status": "INVENTORY_UNAVAILABLE",
            "message": "El inventario no está disponible.",
        },
    )


async def process_payment(
    reservation_id: str,
    payload: ReservationRequest,
) -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                f"{PAYMENT_SERVICE_URL}/payments/process",
                json={
                    "reservation_id": reservation_id,
                    "user_id": payload.user_id,
                    "amount": payload.quantity * 10.0,
                },
            )

        if response.status_code == status.HTTP_200_OK:
            return {
                "status": "CONFIRMED",
                "detail": response.json(),
            }

        logger.warning(
            "Pagos respondió con código %s; se aplicará fallback.",
            response.status_code,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("El Servicio de Pagos no está disponible: %s", exc)

    return {
        "status": "PAYMENT_PENDING",
        "detail": {
            "message": "El pago será procesado posteriormente."
        },
    }


async def send_notification(
    reservation_id: str,
    payload: ReservationRequest,
) -> dict:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.post(
                f"{NOTIFICATION_SERVICE_URL}/notifications/send",
                json={
                    "reservation_id": reservation_id,
                    "user_id": payload.user_id,
                    "message": "Su reserva fue confirmada.",
                },
            )

        if response.status_code == status.HTTP_200_OK:
            return {
                "status": "SENT",
                "detail": response.json(),
            }
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning(
            "El Servicio de Notificaciones no está disponible: %s",
            exc,
        )

    return {
        "status": "NOTIFICATION_PENDING",
        "detail": {
            "message": "La reserva continúa aunque la notificación haya fallado."
        },
    }


@app.get("/")
async def root():
    return {
        "service": "reservation-service",
        "message": "Servicio principal de reservas",
        "instance": INSTANCE_NAME,
    }


@app.get("/health")
async def health():
    try:
        database_check = await asyncio.to_thread(check_database)
        return {
            "status": "ok",
            "service": "reservation-service",
            "database": "connected",
            "database_check": database_check,
            "instance": INSTANCE_NAME,
        }
    except Exception as exc:
        logger.exception("Reservation Service no pudo acceder a PostgreSQL.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base de datos de reservas no está disponible.",
        ) from exc


@app.post("/reservations", status_code=status.HTTP_201_CREATED)
async def create_reservation(payload: ReservationRequest):
    inventory_result = await reserve_inventory(payload)
    reservation_id = str(uuid4())
    payment_result = await process_payment(reservation_id, payload)

    if payment_result["status"] == "CONFIRMED":
        notification_result = await send_notification(reservation_id, payload)
    else:
        notification_result = {
            "status": "NOT_SENT",
            "detail": {
                "message": "Se enviará cuando el pago sea confirmado."
            },
        }

    if payment_result["status"] == "PAYMENT_PENDING":
        final_status = "PAYMENT_PENDING"
    elif notification_result["status"] == "NOTIFICATION_PENDING":
        final_status = "NOTIFICATION_PENDING"
    else:
        final_status = "CONFIRMED"

    try:
        await asyncio.to_thread(
            save_reservation,
            reservation_id,
            payload,
            final_status,
            payment_result["status"],
            notification_result["status"],
        )
    except Exception as exc:
        logger.exception("No se pudo persistir la reserva %s.", reservation_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La reserva no pudo almacenarse en PostgreSQL.",
        ) from exc

    reservation = {
        "reservation_id": reservation_id,
        "event_id": payload.event_id,
        "user_id": payload.user_id,
        "quantity": payload.quantity,
        "status": final_status,
        "inventory": inventory_result,
        "payment": payment_result,
        "notification": notification_result,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instance": INSTANCE_NAME,
    }

    logger.info(
        "Reserva %s creada con estado %s.",
        reservation_id,
        final_status,
    )

    return reservation


@app.get("/reservations")
async def get_reservations():
    try:
        reservations = await asyncio.to_thread(read_reservations)
        return {
            "count": len(reservations),
            "reservations": reservations,
            "instance": INSTANCE_NAME,
        }
    except Exception as exc:
        logger.exception("No se pudieron consultar las reservas.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible consultar las reservas.",
        ) from exc


@app.get("/reservations/{reservation_id}")
async def get_reservation(reservation_id: str):
    try:
        UUID(reservation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El identificador de reserva no es válido.",
        ) from exc

    try:
        reservation = await asyncio.to_thread(
            read_reservation,
            reservation_id,
        )
    except Exception as exc:
        logger.exception("No se pudo consultar la reserva %s.", reservation_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible consultar la reserva.",
        ) from exc

    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reserva no encontrada.",
        )

    reservation["instance"] = INSTANCE_NAME
    return reservation

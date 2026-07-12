import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("reservation-service")

app = FastAPI(
    title="Reservation Service",
    description="Servicio principal encargado de procesar reservas.",
    version="1.0.0",
)

INVENTORY_SERVICE_URL = os.getenv(
    "INVENTORY_SERVICE_URL",
    "http://localhost:8002",
)

PAYMENT_SERVICE_URL = os.getenv(
    "PAYMENT_SERVICE_URL",
    "http://localhost:8003",
)

NOTIFICATION_SERVICE_URL = os.getenv(
    "NOTIFICATION_SERVICE_URL",
    "http://localhost:8004",
)

reservations: dict[str, dict] = {}


class ReservationRequest(BaseModel):
    event_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=10)


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

            if response.status_code == status.HTTP_409_CONFLICT:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No existen suficientes asientos disponibles.",
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

    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning(
            "El Servicio de Pagos no está disponible: %s",
            exc,
        )

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
            "message": "La reserva continúa aunque el correo haya fallado."
        },
    }


@app.get("/")
async def root():
    return {
        "service": "reservation-service",
        "message": "Servicio principal de reservas",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "reservation-service",
    }


@app.post("/reservations")
async def create_reservation(payload: ReservationRequest):
    inventory_result = await reserve_inventory(payload)

    reservation_id = str(uuid4())

    payment_result = await process_payment(
        reservation_id,
        payload,
    )

    if payment_result["status"] == "CONFIRMED":
        notification_result = await send_notification(
            reservation_id,
            payload,
        )
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
    }

    reservations[reservation_id] = reservation

    logger.info(
        "Reserva %s creada con estado %s.",
        reservation_id,
        final_status,
    )

    return reservation


@app.get("/reservations/{reservation_id}")
async def get_reservation(reservation_id: str):
    reservation = reservations.get(reservation_id)

    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reserva no encontrada.",
        )

    return reservation
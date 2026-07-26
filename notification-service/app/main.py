import asyncio
import logging
import math
import os
import time
from uuid import UUID, uuid4

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("notification-service")


def read_notification_delay() -> float:
    raw_value = os.getenv("NOTIFICATION_DELAY_SECONDS", "0")

    try:
        delay = float(raw_value)
    except ValueError:
        logger.warning(
            "NOTIFICATION_DELAY_SECONDS=%r no es valido; se usara 0 segundos.",
            raw_value,
        )
        return 0.0

    if not math.isfinite(delay) or delay < 0:
        logger.warning(
            "NOTIFICATION_DELAY_SECONDS=%r debe ser un numero finito mayor o "
            "igual a 0; se usara 0 segundos.",
            raw_value,
        )
        return 0.0

    return delay


INSTANCE_NAME = os.getenv("INSTANCE_NAME", "notification-local")
NOTIFICATION_DELAY_SECONDS = read_notification_delay()
NOTIFICATION_FAILURE_MODE = os.getenv(
    "NOTIFICATION_FAILURE_MODE",
    "none",
).strip().lower()

if NOTIFICATION_FAILURE_MODE not in {"none", "drop"}:
    logger.warning(
        "NOTIFICATION_FAILURE_MODE=%r no es reconocido; se enviaran "
        "notificaciones normalmente.",
        NOTIFICATION_FAILURE_MODE,
    )
    NOTIFICATION_FAILURE_MODE = "none"

app = FastAPI(
    title="Notification Service",
    description="Servicio encargado de simular el envio de notificaciones.",
    version="1.0.0",
)


class NotificationRequest(BaseModel):
    reservation_id: UUID
    user_id: int = Field(gt=0)
    message: str = Field(min_length=1)


@app.get("/")
async def root():
    return {
        "service": "notification-service",
        "message": "Servicio de Notificaciones",
        "instance": INSTANCE_NAME,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "notification-service",
        "instance": INSTANCE_NAME,
        "delay_seconds": NOTIFICATION_DELAY_SECONDS,
        "failure_mode": NOTIFICATION_FAILURE_MODE,
    }


@app.post("/notifications/send")
async def send_notification(payload: NotificationRequest):
    reservation_id = str(payload.reservation_id)
    started_at = time.monotonic()

    logger.info(
        "Iniciando notificacion. reserva=%s usuario=%s instancia=%s",
        reservation_id,
        payload.user_id,
        INSTANCE_NAME,
    )

    if NOTIFICATION_DELAY_SECONDS > 0:
        logger.info(
            "Notificacion de la reserva %s esperara %.2f segundos.",
            reservation_id,
            NOTIFICATION_DELAY_SECONDS,
        )
        await asyncio.sleep(NOTIFICATION_DELAY_SECONDS)

    elapsed_seconds = time.monotonic() - started_at

    if NOTIFICATION_FAILURE_MODE == "drop":
        logger.warning(
            "Notificacion finalizada. reserva=%s resultado=DROPPED "
            "duracion=%.2fs instancia=%s",
            reservation_id,
            elapsed_seconds,
            INSTANCE_NAME,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "DROPPED",
                "reservation_id": reservation_id,
                "message": "La notificacion no fue enviada.",
                "instance": INSTANCE_NAME,
            },
        )

    notification_id = str(uuid4())

    logger.info(
        "Notificacion finalizada. reserva=%s notificacion=%s resultado=SENT "
        "duracion=%.2fs instancia=%s",
        reservation_id,
        notification_id,
        elapsed_seconds,
        INSTANCE_NAME,
    )

    return {
        "status": "SENT",
        "reservation_id": reservation_id,
        "notification_id": notification_id,
        "instance": INSTANCE_NAME,
    }

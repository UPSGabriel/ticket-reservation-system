import asyncio
import logging
import math
import os
import random
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


def read_number(
    variable_name: str,
    default: float,
    maximum: float | None = None,
) -> float:
    raw_value = os.getenv(variable_name, str(default))

    try:
        value = float(raw_value)
    except ValueError:
        logger.warning(
            "%s=%r no es valido; se usara %s.",
            variable_name,
            raw_value,
            default,
        )
        return default

    if not math.isfinite(value) or value < 0:
        logger.warning(
            "%s=%r debe ser un numero finito mayor o igual a 0; se usara %s.",
            variable_name,
            raw_value,
            default,
        )
        return default

    if maximum is not None and value > maximum:
        logger.warning(
            "%s=%r no puede ser mayor que %s; se usara %s.",
            variable_name,
            raw_value,
            maximum,
            default,
        )
        return default

    return value


INSTANCE_NAME = os.getenv("INSTANCE_NAME", "notification-local")
NOTIFICATION_DELAY_SECONDS = read_number("NOTIFICATION_DELAY_SECONDS", 0.0)
NOTIFICATION_MIN_DELAY_MS = read_number("NOTIFICATION_MIN_DELAY_MS", 50.0)
NOTIFICATION_MAX_DELAY_MS = read_number("NOTIFICATION_MAX_DELAY_MS", 500.0)
NOTIFICATION_FAILURE_RATE = read_number(
    "NOTIFICATION_FAILURE_RATE",
    0.0,
    maximum=1.0,
)
NOTIFICATION_FAILURE_MODE = os.getenv(
    "NOTIFICATION_FAILURE_MODE",
    "none",
).strip().lower()

if NOTIFICATION_MAX_DELAY_MS < NOTIFICATION_MIN_DELAY_MS:
    logger.warning(
        "NOTIFICATION_MAX_DELAY_MS es menor que NOTIFICATION_MIN_DELAY_MS; "
        "se intercambiaran los valores."
    )
    NOTIFICATION_MIN_DELAY_MS, NOTIFICATION_MAX_DELAY_MS = (
        NOTIFICATION_MAX_DELAY_MS,
        NOTIFICATION_MIN_DELAY_MS,
    )

if NOTIFICATION_FAILURE_MODE not in {"none", "drop"}:
    logger.warning(
        "NOTIFICATION_FAILURE_MODE=%r no es reconocido; se enviaran "
        "notificaciones normalmente.",
        NOTIFICATION_FAILURE_MODE,
    )
    NOTIFICATION_FAILURE_MODE = "none"


def select_notification_delay() -> tuple[float, str]:
    if NOTIFICATION_DELAY_SECONDS > 0:
        return NOTIFICATION_DELAY_SECONDS, "fixed"

    delay_ms = random.uniform(
        NOTIFICATION_MIN_DELAY_MS,
        NOTIFICATION_MAX_DELAY_MS,
    )
    return delay_ms / 1000.0, "random"


def select_notification_failure() -> str | None:
    if NOTIFICATION_FAILURE_MODE == "drop":
        return "forced"

    if (
        NOTIFICATION_FAILURE_RATE > 0
        and random.random() < NOTIFICATION_FAILURE_RATE
    ):
        return "random"

    return None


app = FastAPI(
    title="Notification Service",
    description="Servicio encargado de simular el envio de notificaciones.",
    version="1.1.0",
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
        "min_delay_ms": NOTIFICATION_MIN_DELAY_MS,
        "max_delay_ms": NOTIFICATION_MAX_DELAY_MS,
        "failure_rate": NOTIFICATION_FAILURE_RATE,
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

    delay_seconds, delay_source = select_notification_delay()

    if delay_seconds > 0:
        logger.info(
            "Notificacion de la reserva %s esperara %.3f segundos. origen=%s",
            reservation_id,
            delay_seconds,
            delay_source,
        )
        await asyncio.sleep(delay_seconds)

    elapsed_seconds = time.monotonic() - started_at
    failure_source = select_notification_failure()

    if failure_source is not None:
        logger.warning(
            "Notificacion finalizada. reserva=%s resultado=DROPPED "
            "origen_fallo=%s duracion=%.2fs instancia=%s",
            reservation_id,
            failure_source,
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

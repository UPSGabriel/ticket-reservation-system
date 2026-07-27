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

logger = logging.getLogger("payment-service")


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


INSTANCE_NAME = os.getenv("INSTANCE_NAME", "payment-local")
PAYMENT_DELAY_SECONDS = read_number("PAYMENT_DELAY_SECONDS", 0.0)
PAYMENT_MIN_DELAY_MS = read_number("PAYMENT_MIN_DELAY_MS", 100.0)
PAYMENT_MAX_DELAY_MS = read_number("PAYMENT_MAX_DELAY_MS", 800.0)
PAYMENT_FAILURE_RATE = read_number("PAYMENT_FAILURE_RATE", 0.0, maximum=1.0)
PAYMENT_FAILURE_MODE = os.getenv(
    "PAYMENT_FAILURE_MODE",
    "none",
).strip().lower()

if PAYMENT_MAX_DELAY_MS < PAYMENT_MIN_DELAY_MS:
    logger.warning(
        "PAYMENT_MAX_DELAY_MS es menor que PAYMENT_MIN_DELAY_MS; "
        "se intercambiaran los valores."
    )
    PAYMENT_MIN_DELAY_MS, PAYMENT_MAX_DELAY_MS = (
        PAYMENT_MAX_DELAY_MS,
        PAYMENT_MIN_DELAY_MS,
    )

if PAYMENT_FAILURE_MODE not in {"none", "reject"}:
    logger.warning(
        "PAYMENT_FAILURE_MODE=%r no es reconocido; se procesaran pagos normalmente.",
        PAYMENT_FAILURE_MODE,
    )
    PAYMENT_FAILURE_MODE = "none"


def select_payment_delay() -> tuple[float, str]:
    if PAYMENT_DELAY_SECONDS > 0:
        return PAYMENT_DELAY_SECONDS, "fixed"

    delay_ms = random.uniform(PAYMENT_MIN_DELAY_MS, PAYMENT_MAX_DELAY_MS)
    return delay_ms / 1000.0, "random"


def select_payment_failure() -> str | None:
    if PAYMENT_FAILURE_MODE == "reject":
        return "forced"

    if PAYMENT_FAILURE_RATE > 0 and random.random() < PAYMENT_FAILURE_RATE:
        return "random"

    return None


app = FastAPI(
    title="Payment Service",
    description="Servicio encargado de simular el procesamiento de pagos.",
    version="1.1.0",
)


class PaymentRequest(BaseModel):
    reservation_id: UUID
    user_id: int = Field(gt=0)
    amount: float = Field(gt=0)


@app.get("/")
async def root():
    return {
        "service": "payment-service",
        "message": "Servicio de Pagos",
        "instance": INSTANCE_NAME,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "payment-service",
        "instance": INSTANCE_NAME,
        "delay_seconds": PAYMENT_DELAY_SECONDS,
        "min_delay_ms": PAYMENT_MIN_DELAY_MS,
        "max_delay_ms": PAYMENT_MAX_DELAY_MS,
        "failure_rate": PAYMENT_FAILURE_RATE,
        "failure_mode": PAYMENT_FAILURE_MODE,
    }


@app.post("/payments/process")
async def process_payment(payload: PaymentRequest):
    reservation_id = str(payload.reservation_id)
    started_at = time.monotonic()

    logger.info(
        "Iniciando pago. reserva=%s usuario=%s monto=%.2f instancia=%s",
        reservation_id,
        payload.user_id,
        payload.amount,
        INSTANCE_NAME,
    )

    delay_seconds, delay_source = select_payment_delay()

    if delay_seconds > 0:
        logger.info(
            "Pago de la reserva %s esperara %.3f segundos. origen=%s",
            reservation_id,
            delay_seconds,
            delay_source,
        )
        await asyncio.sleep(delay_seconds)

    elapsed_seconds = time.monotonic() - started_at
    failure_source = select_payment_failure()

    if failure_source is not None:
        logger.warning(
            "Pago finalizado. reserva=%s resultado=REJECTED origen_fallo=%s "
            "duracion=%.2fs instancia=%s",
            reservation_id,
            failure_source,
            elapsed_seconds,
            INSTANCE_NAME,
        )
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "status": "REJECTED",
                "reservation_id": reservation_id,
                "amount": payload.amount,
                "message": "El pago fue rechazado por la pasarela.",
                "instance": INSTANCE_NAME,
            },
        )

    transaction_id = str(uuid4())

    logger.info(
        "Pago finalizado. reserva=%s transaccion=%s resultado=APPROVED "
        "duracion=%.2fs instancia=%s",
        reservation_id,
        transaction_id,
        elapsed_seconds,
        INSTANCE_NAME,
    )

    return {
        "status": "APPROVED",
        "reservation_id": reservation_id,
        "transaction_id": transaction_id,
        "amount": payload.amount,
        "instance": INSTANCE_NAME,
    }

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

logger = logging.getLogger("payment-service")


def read_payment_delay() -> float:
    raw_value = os.getenv("PAYMENT_DELAY_SECONDS", "0")

    try:
        delay = float(raw_value)
    except ValueError:
        logger.warning(
            "PAYMENT_DELAY_SECONDS=%r no es valido; se usara 0 segundos.",
            raw_value,
        )
        return 0.0

    if not math.isfinite(delay) or delay < 0:
        logger.warning(
            "PAYMENT_DELAY_SECONDS=%r debe ser un numero finito mayor o igual a 0; "
            "se usara 0 segundos.",
            raw_value,
        )
        return 0.0

    return delay


INSTANCE_NAME = os.getenv("INSTANCE_NAME", "payment-local")
PAYMENT_DELAY_SECONDS = read_payment_delay()
PAYMENT_FAILURE_MODE = os.getenv(
    "PAYMENT_FAILURE_MODE",
    "none",
).strip().lower()

if PAYMENT_FAILURE_MODE not in {"none", "reject"}:
    logger.warning(
        "PAYMENT_FAILURE_MODE=%r no es reconocido; se procesaran pagos normalmente.",
        PAYMENT_FAILURE_MODE,
    )
    PAYMENT_FAILURE_MODE = "none"

app = FastAPI(
    title="Payment Service",
    description="Servicio encargado de simular el procesamiento de pagos.",
    version="1.0.0",
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

    if PAYMENT_DELAY_SECONDS > 0:
        logger.info(
            "Pago de la reserva %s esperara %.2f segundos.",
            reservation_id,
            PAYMENT_DELAY_SECONDS,
        )
        await asyncio.sleep(PAYMENT_DELAY_SECONDS)

    elapsed_seconds = time.monotonic() - started_at

    if PAYMENT_FAILURE_MODE == "reject":
        logger.warning(
            "Pago finalizado. reserva=%s resultado=REJECTED duracion=%.2fs instancia=%s",
            reservation_id,
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

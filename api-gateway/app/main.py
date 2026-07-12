import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from typing import DefaultDict, Deque

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("api-gateway")

app = FastAPI(
    title="Ticket Reservation API Gateway",
    description="Punto de entrada del sistema distribuido de reservas.",
    version="1.0.0",
)

RESERVATION_SERVICE_URL = os.getenv(
    "RESERVATION_SERVICE_URL",
    "http://localhost:8001",
)

RATE_LIMIT_MAX_REQUESTS = int(
    os.getenv("RATE_LIMIT_MAX_REQUESTS", "10")
)

RATE_LIMIT_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_WINDOW_SECONDS", "10")
)

MAX_CONCURRENT_REQUESTS = int(
    os.getenv("MAX_CONCURRENT_REQUESTS", "5")
)

request_history: DefaultDict[str, Deque[float]] = defaultdict(deque)
rate_limit_lock = asyncio.Lock()
bulkhead = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)


class ReservationRequest(BaseModel):
    event_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=10)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    excluded_paths = {
        "/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    if request.url.path in excluded_paths:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    current_time = time.monotonic()

    async with rate_limit_lock:
        history = request_history[client_ip]

        while (
            history
            and current_time - history[0]
            > RATE_LIMIT_WINDOW_SECONDS
        ):
            history.popleft()

        if len(history) >= RATE_LIMIT_MAX_REQUESTS:
            logger.warning(
                "Solicitud rechazada por rate limiting. Cliente: %s",
                client_ip,
            )

            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "status": "REJECTED",
                    "message": "Demasiadas solicitudes. Intente nuevamente.",
                },
            )

        history.append(current_time)

    return await call_next(request)


@app.get("/")
async def root():
    return {
        "service": "api-gateway",
        "message": "Sistema distribuido de reservas de entradas",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "api-gateway",
    }


@app.post("/api/reservations")
async def create_reservation(payload: ReservationRequest):
    acquired = False

    try:
        await asyncio.wait_for(
            bulkhead.acquire(),
            timeout=0.05,
        )
        acquired = True

    except TimeoutError as exc:
        logger.warning(
            "Solicitud rechazada porque el bulkhead está lleno."
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El Gateway está ocupado. Intente nuevamente.",
        ) from exc

    try:
        logger.info(
            "Enviando reserva al servicio Core: %s",
            payload.model_dump(),
        )

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{RESERVATION_SERVICE_URL}/reservations",
                json=payload.model_dump(),
            )

        if response.status_code >= 500:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El Servicio de Reservas no está disponible.",
            )

        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.text,
            )

        return response.json()

    except httpx.TimeoutException as exc:
        logger.error(
            "Timeout al comunicarse con reservation-service."
        )

        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="El Servicio de Reservas tardó demasiado en responder.",
        ) from exc

    except httpx.RequestError as exc:
        logger.error(
            "No se pudo conectar con reservation-service: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El Servicio de Reservas no está disponible.",
        ) from exc

    finally:
        if acquired:
            bulkhead.release()
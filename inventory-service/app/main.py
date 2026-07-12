import asyncio
import logging
import os

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("inventory-service")

app = FastAPI(
    title="Inventory Service",
    description="Servicio encargado de consultar y descontar asientos.",
    version="1.0.0",
)

INSTANCE_NAME = os.getenv("HOSTNAME", "inventory-local")

inventory: dict[int, int] = {
    1: 100,
    2: 50,
    3: 1,
}

inventory_lock = asyncio.Lock()


class InventoryRequest(BaseModel):
    event_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=10)


@app.get("/")
async def root():
    return {
        "service": "inventory-service",
        "message": "Servicio de Inventario",
        "instance": INSTANCE_NAME,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "inventory-service",
        "instance": INSTANCE_NAME,
    }


@app.get("/inventory")
async def get_all_inventory():
    return {
        "inventory": inventory,
        "instance": INSTANCE_NAME,
    }


@app.get("/inventory/{event_id}")
async def get_inventory(event_id: int):
    if event_id not in inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento no encontrado.",
        )

    return {
        "event_id": event_id,
        "available": inventory[event_id],
        "instance": INSTANCE_NAME,
    }


@app.post("/inventory/reserve")
async def reserve_inventory(payload: InventoryRequest):
    async with inventory_lock:
        if payload.event_id not in inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evento no encontrado.",
            )

        available = inventory[payload.event_id]

        if available < payload.quantity:
            logger.warning(
                "Inventario insuficiente. Evento: %s, disponible: %s, solicitado: %s",
                payload.event_id,
                available,
                payload.quantity,
            )

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "status": "INSUFFICIENT_INVENTORY",
                    "message": "No existen suficientes asientos disponibles.",
                    "available": available,
                },
            )

        inventory[payload.event_id] -= payload.quantity

        remaining = inventory[payload.event_id]

        logger.info(
            "Inventario reservado. Evento: %s, cantidad: %s, restante: %s, instancia: %s",
            payload.event_id,
            payload.quantity,
            remaining,
            INSTANCE_NAME,
        )

        return {
            "status": "RESERVED",
            "event_id": payload.event_id,
            "quantity": payload.quantity,
            "remaining": remaining,
            "instance": INSTANCE_NAME,
        }


@app.post("/inventory/reset")
async def reset_inventory():
    inventory.clear()
    inventory.update({
        1: 100,
        2: 50,
        3: 1,
    })

    logger.info("Inventario reiniciado.")

    return {
        "status": "RESET",
        "inventory": inventory,
        "instance": INSTANCE_NAME,
    }
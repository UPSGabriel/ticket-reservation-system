import logging
import os

import psycopg
from fastapi import FastAPI, HTTPException, status
from psycopg.rows import dict_row
from pydantic import BaseModel, Field


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("inventory-service")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ticket_user:ticket_pass@127.0.0.1:5432/ticket_db",
)

INSTANCE_NAME = os.getenv("HOSTNAME", "inventory-local")

app = FastAPI(
    title="Inventory Service",
    description="Servicio encargado de consultar y descontar asientos con PostgreSQL.",
    version="1.2.0",
)


class InventoryRequest(BaseModel):
    event_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=10)


def open_connection() -> psycopg.Connection:
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=5,
        row_factory=dict_row,
        sslmode="disable",
    )


@app.get("/")
def root():
    return {
        "service": "inventory-service",
        "message": "Servicio de Inventario con PostgreSQL",
        "instance": INSTANCE_NAME,
    }


@app.get("/health")
def health():
    try:
        with open_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS result;")
                row = cursor.fetchone()

        return {
            "status": "ok",
            "service": "inventory-service",
            "database": "connected",
            "database_check": row["result"] if row else None,
            "instance": INSTANCE_NAME,
        }
    except Exception as exc:
        logger.exception("No se pudo conectar con PostgreSQL.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"La base de datos no está disponible: {type(exc).__name__}",
        ) from exc


@app.get("/inventory")
def get_all_inventory():
    try:
        with open_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.event_id,
                        e.name,
                        e.price,
                        i.available,
                        i.updated_at
                    FROM inventory AS i
                    INNER JOIN events AS e ON e.id = i.event_id
                    ORDER BY i.event_id;
                    """
                )
                rows = cursor.fetchall()

        return {
            "inventory": rows,
            "instance": INSTANCE_NAME,
        }
    except Exception as exc:
        logger.exception("Error consultando el inventario.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible consultar el inventario.",
        ) from exc


@app.get("/inventory/{event_id}")
def get_inventory(event_id: int):
    try:
        with open_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.event_id,
                        e.name,
                        e.price,
                        i.available,
                        i.updated_at
                    FROM inventory AS i
                    INNER JOIN events AS e ON e.id = i.event_id
                    WHERE i.event_id = %s;
                    """,
                    (event_id,),
                )
                row = cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evento no encontrado.",
            )

        row["instance"] = INSTANCE_NAME
        return row
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error consultando el evento %s.", event_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible consultar el inventario.",
        ) from exc


@app.post("/inventory/reserve")
def reserve_inventory(payload: InventoryRequest):
    try:
        with open_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE inventory
                    SET
                        available = available - %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE event_id = %s
                      AND available >= %s
                    RETURNING available;
                    """,
                    (payload.quantity, payload.event_id, payload.quantity),
                )
                row = cursor.fetchone()

                if row is None:
                    cursor.execute(
                        "SELECT available FROM inventory WHERE event_id = %s;",
                        (payload.event_id,),
                    )
                    current = cursor.fetchone()

                    if current is None:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Evento no encontrado.",
                        )

                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "status": "INSUFFICIENT_INVENTORY",
                            "message": "No existen suficientes asientos disponibles.",
                            "available": current["available"],
                        },
                    )

                remaining = row["available"]

        logger.info(
            "Inventario reservado. Evento=%s cantidad=%s restante=%s instancia=%s",
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
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error reservando inventario.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible procesar la reserva de inventario.",
        ) from exc


@app.post("/inventory/reset")
def reset_inventory():
    try:
        with open_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE inventory
                    SET
                        available = CASE event_id
                            WHEN 1 THEN 100
                            WHEN 2 THEN 50
                            WHEN 3 THEN 1
                            ELSE available
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE event_id IN (1, 2, 3);
                    """
                )

                cursor.execute(
                    "SELECT event_id, available FROM inventory ORDER BY event_id;"
                )
                rows = cursor.fetchall()

        logger.info("Inventario reiniciado correctamente.")

        return {
            "status": "RESET",
            "inventory": rows,
            "instance": INSTANCE_NAME,
        }
    except Exception as exc:
        logger.exception("Error reiniciando el inventario.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible reiniciar el inventario.",
        ) from exc

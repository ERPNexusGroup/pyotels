"""Admin generic CRUD endpoints for any mapped entity."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import DateTime, Numeric, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import (
    ApiKey,
    Category,
    Guest,
    Hotel,
    Reservation,
    Room,
)
from otelms.domain.entities import Base as EntityBase
from otelms.utils.logging import get_logger

from .auth import _admin_enabled, _get_db, _require_admin

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


# Dynamic mapping of CRUD slugs to SQLAlchemy model entities
_CRUD_MODELS: dict[str, type[EntityBase]] = {
    "hotels": Hotel,
    "categories": Category,
    "rooms": Room,
    "reservations": Reservation,
    "guests": Guest,
    "api-keys": ApiKey,
}


class RowUpdatePayload(BaseModel):
    """Generic payload for row updates in the admin CRUD."""

    data: dict[str, Any]


def _cast_payload_values(model: type[EntityBase], data: dict[str, Any]) -> dict[str, Any]:
    """Cast payload values to appropriate Python types based on SQLAlchemy column types.

    Handles:
    - DateTime: parses ISO format strings to datetime objects
    - Numeric/Decimal: converts strings to Decimal
    - Boolean: ensures proper bool type
    - Others: left as-is
    """
    casted: dict[str, Any] = {}
    for col in model.__table__.columns:
        if col.name in data and data[col.name] is not None:
            val = data[col.name]
            if isinstance(col.type, DateTime) and isinstance(val, str):
                # Handle ISO format strings, including 'Z' suffix
                casted[col.name] = datetime.fromisoformat(val.replace("Z", "+00:00"))
            elif isinstance(col.type, Numeric) and val != "":
                casted[col.name] = Decimal(str(val))
            else:
                casted[col.name] = val
    return casted


@router.get("/api/tables/{table_slug}")
async def admin_list_table(
    table_slug: str,
    hotel_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Lista filas de una tabla con paginación y filtro opcional por hotel."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    model = _CRUD_MODELS.get(table_slug)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = select(model)
    if hotel_id and hasattr(model, "hotel_id"):
        stmt = stmt.where(model.hotel_id == hotel_id)

    # Total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    # Paginated
    stmt = stmt.order_by(model.id).limit(limit).offset(offset)  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Convert to dict
    items = []
    for row in rows:
        item = {}
        for col in model.__table__.columns:
            val = getattr(row, col.name)
            if isinstance(val, datetime):
                item[col.name] = val.isoformat() if val else None
            elif isinstance(val, Decimal):
                item[col.name] = str(val)
            else:
                item[col.name] = val
        items.append(item)

    return {
        "table": table_slug,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/tables/{table_slug}/{id}")
async def admin_get_row(
    table_slug: str,
    id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Obtiene una fila por ID."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    model = _CRUD_MODELS.get(table_slug)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    stmt = select(model).where(model.id == id)  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Row not found")

    item = {}
    for col in model.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, datetime):
            item[col.name] = val.isoformat() if val else None
        elif isinstance(val, Decimal):
                        item[col.name] = str(val)
        else:
            item[col.name] = val

    return item


@router.post("/api/tables/{table_slug}", status_code=status.HTTP_201_CREATED)
async def admin_create_row(
    table_slug: str,
    payload: RowUpdatePayload,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Crea una nueva fila."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    model = _CRUD_MODELS.get(table_slug)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    casted_data = _cast_payload_values(model, payload.data)
    row = model(**casted_data)
    session.add(row)
    await session.flush()
    await session.commit()

    return {"id": row.id, "table": table_slug}  # type: ignore[attr-defined]


@router.put("/api/tables/{table_slug}/{id}")
async def admin_update_row(
    table_slug: str,
    id: str,
    payload: RowUpdatePayload,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Actualiza una fila existente."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    model = _CRUD_MODELS.get(table_slug)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    stmt = select(model).where(model.id == id)  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Row not found")

    casted_data = _cast_payload_values(model, payload.data)
    for key, value in casted_data.items():
        setattr(row, key, value)

    await session.flush()
    await session.commit()

    return {"id": row.id, "table": table_slug, "updated": True}  # type: ignore[attr-defined]


@router.delete("/api/tables/{table_slug}/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_row(
    table_slug: str,
    id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> None:
    """Elimina una fila."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    model = _CRUD_MODELS.get(table_slug)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    stmt = select(model).where(model.id == id)  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Row not found")

    await session.delete(row)
    await session.commit()

"""
WebSocket endpoints for real-time sync progress.
"""
import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.api.dependencies import get_db
from otelms.config.settings import settings
from otelms.domain.entities import ApiKey
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/ws", tags=["websockets"])
logger = get_logger(__name__)


class ConnectionManager:
    """Manage WebSocket connections for sync progress."""

    def __init__(self) -> None:
        self.active_connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, hotel_id: str) -> None:
        await websocket.accept()
        if hotel_id not in self.active_connections:
            self.active_connections[hotel_id] = set()
        self.active_connections[hotel_id].add(websocket)
        logger.info("WebSocket connected", hotel_id=hotel_id, total=len(self.active_connections[hotel_id]))

    def disconnect(self, websocket: WebSocket, hotel_id: str) -> None:
        if hotel_id in self.active_connections:
            self.active_connections[hotel_id].discard(websocket)
            if not self.active_connections[hotel_id]:
                del self.active_connections[hotel_id]
        logger.info("WebSocket disconnected", hotel_id=hotel_id)

    async def send_progress(self, hotel_id: str, message: dict) -> None:
        """Send progress message to all connections for a hotel."""
        if hotel_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[hotel_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.add(connection)

            # Clean up disconnected
            for conn in disconnected:
                self.active_connections[hotel_id].discard(conn)


# Global connection manager
manager = ConnectionManager()


async def _authenticate_ws(
    session: AsyncSession,
    header_api_key: str | None,
    query_api_key: str | None,
    token: str | None,
) -> ApiKey | dict | None:
    """Validate WebSocket credentials via X-API-Key header/query or admin JWT token."""
    if not settings.api_key_required:
        return ApiKey(
            id="local-test",
            name="Local Testing (API Key Disabled)",
            key_hash="",
            is_active=True,
            rate_limit=60,
        )

    raw_key = header_api_key or query_api_key
    if raw_key:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active)
        result = await session.execute(stmt)
        key_obj = result.scalar_one_or_none()
        if key_obj:
            return key_obj

    if token:
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            if payload.get("role") == "admin":
                return payload
        except JWTError:
            pass

    return None


@router.websocket("/sync-progress")
async def websocket_sync_progress(
    websocket: WebSocket,
    hotel_id: str,
    x_api_key: str | None = Header(None, alias=settings.api_key_header),
    api_key: str | None = Query(None),
    token: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> None:
    """WebSocket endpoint for real-time sync progress updates.

    Query params:
    - hotel_id: Hotel ID to track progress for
    - api_key: API key (alternative to X-API-Key header)
    - token: Admin session JWT (alternative auth)

    Message format (server -> client):
    {
        "type": "progress|complete|error",
        "hotel_id": "hotel_1",
        "sync_type": "calendar|categories|full",
        "progress": 0.5,
        "message": "Syncing calendar...",
        "timestamp": "2026-01-15T10:30:00Z"
    }
    """
    auth = await _authenticate_ws(session, x_api_key, api_key, token)
    if auth is None:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket, hotel_id)

    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "hotel_id": hotel_id,
            "message": f"Connected to sync progress for hotel {hotel_id}",
            "timestamp": datetime.utcnow().isoformat()
        })

        # Keep connection alive, listen for client messages (ping/pong)
        while True:
            data = await websocket.receive_text()
            # Handle ping/pong or client messages
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(websocket, hotel_id)
    except Exception as e:
        logger.error("WebSocket error", hotel_id=hotel_id, error=str(e))
        manager.disconnect(websocket, hotel_id)


# Function to be called from SyncService to broadcast progress
async def broadcast_sync_progress(
    hotel_id: str, sync_type: str, progress: float, message: str,
    status: str = "progress",
) -> None:
    """Broadcast sync progress to WebSocket clients."""
    await manager.send_progress(hotel_id, {
        "type": status,  # progress, complete, error
        "hotel_id": hotel_id,
        "sync_type": sync_type,
        "progress": progress,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    })

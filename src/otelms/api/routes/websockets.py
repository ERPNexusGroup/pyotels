"""
WebSocket endpoints for real-time sync progress.
"""
import asyncio
import json
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from datetime import datetime

from otelms.api.dependencies import verify_api_key
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/ws", tags=["websockets"])
logger = get_logger(__name__)


class ConnectionManager:
    """Manage WebSocket connections for sync progress."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, hotel_id: str):
        await websocket.accept()
        if hotel_id not in self.active_connections:
            self.active_connections[hotel_id] = set()
        self.active_connections[hotel_id].add(websocket)
        logger.info("WebSocket connected", hotel_id=hotel_id, total=len(self.active_connections[hotel_id]))

    def disconnect(self, websocket: WebSocket, hotel_id: str):
        if hotel_id in self.active_connections:
            self.active_connections[hotel_id].discard(websocket)
            if not self.active_connections[hotel_id]:
                del self.active_connections[hotel_id]
        logger.info("WebSocket disconnected", hotel_id=hotel_id)

    async def send_progress(self, hotel_id: str, message: dict):
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


@router.websocket("/sync-progress")
async def websocket_sync_progress(
    websocket: WebSocket,
    hotel_id: str,
    api_key: str = Depends(verify_api_key),
):
    """WebSocket endpoint for real-time sync progress updates.
    
    Query params:
    - hotel_id: Hotel ID to track progress for
    
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
async def broadcast_sync_progress(hotel_id: str, sync_type: str, progress: float, message: str, status: str = "progress"):
    """Broadcast sync progress to WebSocket clients."""
    await manager.send_progress(hotel_id, {
        "type": status,  # progress, complete, error
        "hotel_id": hotel_id,
        "sync_type": sync_type,
        "progress": progress,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    })
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.logging import get_logger
from core.redis import get_redis_pool

logger = get_logger(__name__)

router = APIRouter()


class ConnectionManager:
    """
    WebSocket Connection Manager for broadcasting real-time pipeline updates.
    Manages active WebSocket connections and listens to a Redis Pub/Sub channel
    to broadcast events to all connected clients.
    """

    def __init__(self) -> None:
        """Initialize the ConnectionManager with an empty list of active connections."""
        self.active_connections: List[WebSocket] = []
        self.redis_listener_task: Optional[asyncio.Task[None]] = None

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept a new WebSocket connection and add it to the active list.
        Starts the Redis listener task if it is not already running.

        Args:
            websocket (WebSocket): The incoming WebSocket connection.
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            "New WebSocket connection accepted",
            extra={"total_connections": len(self.active_connections)}
        )

        if self.redis_listener_task is None or self.redis_listener_task.done():
            self.redis_listener_task = asyncio.create_task(self.listen_to_redis())

    def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection from the active list.

        Args:
            websocket (WebSocket): The WebSocket connection to remove.
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                "WebSocket connection removed",
                extra={"total_connections": len(self.active_connections)}
            )

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """
        Broadcast a JSON message to all active WebSocket connections.
        Automatically disconnects clients that fail to receive the message.

        Args:
            message (Dict[str, Any]): The JSON-serializable message payload.
        """
        disconnected_clients: List[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(
                    "Failed to send message to WebSocket client, marking for removal",
                    extra={"error": str(e)}
                )
                disconnected_clients.append(connection)

        for failed_connection in disconnected_clients:
            self.disconnect(failed_connection)

    async def listen_to_redis(self) -> None:
        """
        Background task that subscribes to the 'pipeline_updates' Redis channel.
        Listens for incoming messages and broadcasts them to all connected WebSockets.
        """
        try:
            redis_client = await get_redis_pool()
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("pipeline_updates")
            
            logger.info("Subscribed to Redis channel: pipeline_updates")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self.broadcast(data)
                    except json.JSONDecodeError as e:
                        logger.error(
                            "Failed to decode Redis message as JSON",
                            extra={"error": str(e), "raw_data": message["data"]}
                        )
        except asyncio.CancelledError:
            logger.info("Redis listener task cancelled")
        except Exception as e:
            logger.error(
                "Error in Redis Pub/Sub listener",
                extra={"error": str(e)}
            )
        finally:
            self.redis_listener_task = None


manager = ConnectionManager()


async def heartbeat(websocket: WebSocket) -> None:
    """
    Background task to send periodic ping messages to a WebSocket client.
    Prevents the connection from timing out due to inactivity.

    Args:
        websocket (WebSocket): The active WebSocket connection.
    """
    try:
        while True:
            await asyncio.sleep(30)
            ping_message = {
                "event": "heartbeat",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await websocket.send_json(ping_message)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(
            "Heartbeat task encountered an error",
            extra={"error": str(e)}
        )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time pipeline updates.
    Clients connecting to this endpoint will receive broadcasted events
    from the AI processing pipeline.

    Args:
        websocket (WebSocket): The incoming WebSocket connection.
    """
    await manager.connect(websocket)
    heartbeat_task = asyncio.create_task(heartbeat(websocket))

    try:
        while True:
            client_message = await websocket.receive_text()
            logger.debug(
                "Received message from WebSocket client",
                extra={"message": client_message}
            )
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally")
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(
            "Unexpected error in WebSocket endpoint",
            extra={"error": str(e)}
        )
        manager.disconnect(websocket)
    finally:
        heartbeat_task.cancel()
"""
WebSocket Connection Manager
Broadcasts real-time events to connected frontend clients.
"""
from __future__ import annotations
import json
from typing import Any

import structlog
from fastapi import WebSocket

log = structlog.get_logger()


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        # Topic subscriptions: client_id -> set of topics
        self._subscriptions: dict[str, set[str]] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self._connections[client_id] = websocket
        self._subscriptions[client_id] = set()
        log.info("WebSocket connected", client_id=client_id)

    def disconnect(self, client_id: str):
        self._connections.pop(client_id, None)
        self._subscriptions.pop(client_id, None)
        log.info("WebSocket disconnected", client_id=client_id)

    def subscribe(self, client_id: str, topic: str):
        """Subscribe a client to a topic (e.g., run_id or session_id)."""
        if client_id in self._subscriptions:
            self._subscriptions[client_id].add(topic)

    async def send_to(self, client_id: str, data: dict[str, Any]):
        """Send message to specific client."""
        ws = self._connections.get(client_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                self.disconnect(client_id)

    async def broadcast_json(self, data: dict[str, Any]):
        """Broadcast to all connected clients."""
        if not self._connections:
            return
        message = json.dumps(data, default=str)
        dead = []
        for client_id, ws in list(self._connections.items()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(client_id)
        for client_id in dead:
            self.disconnect(client_id)

    async def broadcast_to_subscribers(self, topic: str, data: dict[str, Any]):
        """Broadcast to clients subscribed to a specific topic."""
        message = json.dumps(data, default=str)
        dead = []
        for client_id, topics in list(self._subscriptions.items()):
            if topic in topics:
                ws = self._connections.get(client_id)
                if ws:
                    try:
                        await ws.send_text(message)
                    except Exception:
                        dead.append(client_id)
        for client_id in dead:
            self.disconnect(client_id)

    @property
    def connected_count(self) -> int:
        return len(self._connections)


connection_manager = ConnectionManager()

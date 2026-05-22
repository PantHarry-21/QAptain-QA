import json
from fastapi import WebSocket, WebSocketDisconnect
import structlog

from app.realtime.manager import connection_manager

log = structlog.get_logger()


async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket handler. Clients can:
    - Connect to receive all broadcasts
    - Send {"subscribe": "topic_id"} to filter events
    - Send {"ping": true} for keepalive
    """
    await connection_manager.connect(websocket, client_id)

    try:
        await websocket.send_text(json.dumps({
            "event": "connected",
            "client_id": client_id,
            "message": "QAptain real-time connected",
        }))

        while True:
            try:
                raw = await websocket.receive_text()
                message = json.loads(raw)

                if "subscribe" in message:
                    topic = message["subscribe"]
                    connection_manager.subscribe(client_id, topic)
                    await websocket.send_text(json.dumps({
                        "event": "subscribed",
                        "topic": topic,
                    }))
                elif message.get("ping"):
                    await websocket.send_text(json.dumps({"event": "pong"}))

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        connection_manager.disconnect(client_id)
    except Exception as e:
        log.warning("WebSocket error", client_id=client_id, error=str(e))
        connection_manager.disconnect(client_id)

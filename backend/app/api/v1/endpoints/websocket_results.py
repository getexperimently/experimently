"""
WebSocket endpoint for EP-058: Real-time WebSocket Streaming Results.

Provides a WebSocket endpoint for streaming live experiment results to clients,
along with HTTP companion endpoints for subscriber counts and active experiments.

WebSocket protocol:
  - Client connects to ws://host/api/v1/ws/experiments/{experiment_id}/results
  - Server sends an initial snapshot on connection
  - Server sends periodic updates every RESULTS_STREAM_INTERVAL_SECONDS seconds
  - Client can send {"action": "ping"} -> server replies {"event": "pong"}
  - Client can send {"action": "refresh"} -> server immediately sends fresh snapshot
  - On disconnect: connection is cleaned up automatically
"""

import asyncio
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.services.websocket_manager import ConnectionManager
from backend.app.services.results_streaming_service import ResultsStreamingService

logger = logging.getLogger(__name__)

# How often (in seconds) to push periodic updates to connected clients.
# Configurable via environment variable for testing / tuning.
RESULTS_STREAM_INTERVAL_SECONDS = int(
    os.getenv("RESULTS_STREAM_INTERVAL_SECONDS", "30")
)

router = APIRouter()

# Module-level singleton so all requests share the same ConnectionManager state.
manager = ConnectionManager()


@router.websocket("/ws/experiments/{experiment_id}/results")
async def stream_results(
    websocket: WebSocket,
    experiment_id: str,
) -> None:
    """
    Stream live experiment results over WebSocket.

    Sends an initial snapshot on connection, then periodic updates every
    RESULTS_STREAM_INTERVAL_SECONDS seconds. Also responds to client messages:
      {"action": "ping"} -> {"event": "pong"}
      {"action": "refresh"} -> immediate fresh snapshot
    """
    from backend.app.db.session import SessionLocal

    await manager.connect(websocket, experiment_id)
    streaming_service = ResultsStreamingService(SessionLocal)

    try:
        # Send initial snapshot immediately on connection
        snapshot = await streaming_service.get_live_snapshot(experiment_id)
        await websocket.send_text(json.dumps(snapshot))

        # Main loop: wait for client messages, send periodic updates on timeout
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=float(RESULTS_STREAM_INTERVAL_SECONDS),
                )
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    msg = {}

                action = msg.get("action")
                if action == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
                elif action == "refresh":
                    snapshot = await streaming_service.get_live_snapshot(experiment_id)
                    await websocket.send_text(json.dumps(snapshot))
                else:
                    logger.debug(
                        "Unknown WebSocket action '%s' for experiment %s",
                        action,
                        experiment_id,
                    )

            except asyncio.TimeoutError:
                # Periodic update: interval elapsed without client message
                snapshot = await streaming_service.get_live_snapshot(experiment_id)
                await websocket.send_text(json.dumps(snapshot))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for experiment %s", experiment_id)
    except Exception as exc:
        logger.exception(
            "Unexpected error in WebSocket handler for experiment %s: %s",
            experiment_id,
            exc,
        )
    finally:
        await manager.disconnect(websocket, experiment_id)


@router.get("/ws/experiments/{experiment_id}/results/subscribers")
async def get_subscriber_count(experiment_id: str) -> dict:
    """
    Return the number of active WebSocket subscribers for an experiment.

    No authentication required — informational endpoint.
    """
    return {
        "experiment_id": experiment_id,
        "subscriber_count": manager.subscriber_count(experiment_id),
    }


@router.get("/ws/active-experiments")
async def get_active_experiments() -> dict:
    """
    Return the list of experiment IDs that currently have active WebSocket subscribers.

    No authentication required — informational endpoint.
    """
    return {"active_experiments": manager.active_experiments}

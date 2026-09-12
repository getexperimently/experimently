"""
WebSocket Connection Manager for EP-058: Real-time WebSocket Streaming Results.

Manages WebSocket connections per experiment, enabling live result broadcasting
to all subscribed clients.
"""

import asyncio
import json
import logging
from collections import defaultdict
from typing import Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections grouped by experiment ID.

    Thread-safe using asyncio.Lock for concurrent connection handling.
    """

    def __init__(self) -> None:
        # experiment_id -> set of active WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        experiment_id: str,
        subprotocol: Optional[str] = None,
    ) -> None:
        """Accept a new WebSocket connection and register it for the given experiment."""
        await websocket.accept(subprotocol=subprotocol)
        async with self._lock:
            self._connections[experiment_id].add(websocket)
        logger.info(
            "WebSocket connected for experiment %s. Total subscribers: %d",
            experiment_id,
            self.subscriber_count(experiment_id),
        )

    async def disconnect(self, websocket: WebSocket, experiment_id: str) -> None:
        """Remove a WebSocket connection from the experiment's subscriber set."""
        async with self._lock:
            self._connections[experiment_id].discard(websocket)
            if not self._connections[experiment_id]:
                del self._connections[experiment_id]
        logger.info(
            "WebSocket disconnected for experiment %s. Remaining subscribers: %d",
            experiment_id,
            self.subscriber_count(experiment_id),
        )

    async def broadcast(self, experiment_id: str, message: dict) -> None:
        """
        Send a JSON message to all subscribers of this experiment.

        Dead connections (those that raise on send) are automatically removed.
        """
        payload = json.dumps(message)
        dead: Set[WebSocket] = set()

        async with self._lock:
            conns = set(self._connections.get(experiment_id, set()))

        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.warning(
                    "Failed to send to WebSocket for experiment %s: %s",
                    experiment_id,
                    exc,
                )
                dead.add(ws)

        for ws in dead:
            await self.disconnect(ws, experiment_id)

    def subscriber_count(self, experiment_id: str) -> int:
        """Return the number of active subscribers for a given experiment."""
        return len(self._connections.get(experiment_id, set()))

    @property
    def active_experiments(self) -> list:
        """Return list of experiment IDs that currently have active subscribers."""
        return list(self._connections.keys())

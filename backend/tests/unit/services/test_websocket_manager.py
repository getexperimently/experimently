"""
Unit tests for ConnectionManager (EP-058: Real-time WebSocket Streaming Results).

Tests cover:
- connect / disconnect lifecycle
- broadcast to all subscribers
- dead connection cleanup on broadcast error
- subscriber_count
- active_experiments property
- concurrent connections
- empty experiment cleanup
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.websocket_manager import ConnectionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_websocket(send_raises: bool = False) -> AsyncMock:
    """Create a mock WebSocket."""
    ws = AsyncMock()
    if send_raises:
        ws.send_text.side_effect = Exception("connection closed")
    return ws


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_accepts_websocket():
    """connect() calls websocket.accept()."""
    manager = ConnectionManager()
    ws = _make_websocket()
    await manager.connect(ws, "exp-1")
    ws.accept.assert_called_once()


@pytest.mark.asyncio
async def test_connect_adds_to_connections():
    """connect() registers the WebSocket under the given experiment_id."""
    manager = ConnectionManager()
    ws = _make_websocket()
    await manager.connect(ws, "exp-1")
    assert manager.subscriber_count("exp-1") == 1


@pytest.mark.asyncio
async def test_connect_multiple_clients_same_experiment():
    """Multiple WebSockets can connect to the same experiment."""
    manager = ConnectionManager()
    ws1 = _make_websocket()
    ws2 = _make_websocket()
    ws3 = _make_websocket()
    await manager.connect(ws1, "exp-1")
    await manager.connect(ws2, "exp-1")
    await manager.connect(ws3, "exp-1")
    assert manager.subscriber_count("exp-1") == 3


@pytest.mark.asyncio
async def test_connect_multiple_experiments():
    """Different experiments have independent subscriber sets."""
    manager = ConnectionManager()
    ws1 = _make_websocket()
    ws2 = _make_websocket()
    await manager.connect(ws1, "exp-1")
    await manager.connect(ws2, "exp-2")
    assert manager.subscriber_count("exp-1") == 1
    assert manager.subscriber_count("exp-2") == 1


@pytest.mark.asyncio
async def test_connect_same_ws_different_experiments():
    """A single WebSocket object can be registered for multiple experiments."""
    manager = ConnectionManager()
    ws = _make_websocket()
    await manager.connect(ws, "exp-1")
    await manager.connect(ws, "exp-2")
    assert manager.subscriber_count("exp-1") == 1
    assert manager.subscriber_count("exp-2") == 1


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_removes_connection():
    """disconnect() removes the WebSocket from the experiment's subscriber set."""
    manager = ConnectionManager()
    ws = _make_websocket()
    await manager.connect(ws, "exp-1")
    await manager.disconnect(ws, "exp-1")
    assert manager.subscriber_count("exp-1") == 0


@pytest.mark.asyncio
async def test_disconnect_removes_experiment_key_when_empty():
    """When the last subscriber disconnects, the experiment key is deleted."""
    manager = ConnectionManager()
    ws = _make_websocket()
    await manager.connect(ws, "exp-1")
    await manager.disconnect(ws, "exp-1")
    assert "exp-1" not in manager.active_experiments


@pytest.mark.asyncio
async def test_disconnect_does_not_remove_other_subscribers():
    """Disconnecting one WebSocket leaves others subscribed."""
    manager = ConnectionManager()
    ws1 = _make_websocket()
    ws2 = _make_websocket()
    await manager.connect(ws1, "exp-1")
    await manager.connect(ws2, "exp-1")
    await manager.disconnect(ws1, "exp-1")
    assert manager.subscriber_count("exp-1") == 1


@pytest.mark.asyncio
async def test_disconnect_nonexistent_is_safe():
    """disconnect() on a WebSocket that was never connected is a no-op."""
    manager = ConnectionManager()
    ws = _make_websocket()
    # Should not raise
    await manager.disconnect(ws, "exp-never-connected")


@pytest.mark.asyncio
async def test_disconnect_wrong_experiment_is_safe():
    """disconnect() with wrong experiment_id doesn't affect other experiments."""
    manager = ConnectionManager()
    ws = _make_websocket()
    await manager.connect(ws, "exp-1")
    # Disconnect from non-existent experiment — should not crash
    await manager.disconnect(ws, "exp-2")
    assert manager.subscriber_count("exp-1") == 1


# ---------------------------------------------------------------------------
# broadcast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_subscribers():
    """broadcast() sends the JSON payload to all connected WebSockets."""
    manager = ConnectionManager()
    ws1 = _make_websocket()
    ws2 = _make_websocket()
    await manager.connect(ws1, "exp-1")
    await manager.connect(ws2, "exp-1")

    message = {"event": "results_update", "data": "test"}
    await manager.broadcast("exp-1", message)

    expected = json.dumps(message)
    ws1.send_text.assert_called_once_with(expected)
    ws2.send_text.assert_called_once_with(expected)


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections():
    """broadcast() removes WebSockets that raise on send."""
    manager = ConnectionManager()
    alive_ws = _make_websocket()
    dead_ws = _make_websocket(send_raises=True)
    await manager.connect(alive_ws, "exp-1")
    await manager.connect(dead_ws, "exp-1")

    await manager.broadcast("exp-1", {"event": "test"})

    # Dead WebSocket should have been removed
    assert manager.subscriber_count("exp-1") == 1


@pytest.mark.asyncio
async def test_broadcast_to_nonexistent_experiment_is_safe():
    """broadcast() to an experiment with no subscribers is a no-op."""
    manager = ConnectionManager()
    # Should not raise
    await manager.broadcast("exp-no-subscribers", {"event": "test"})


@pytest.mark.asyncio
async def test_broadcast_sends_json_string():
    """broadcast() sends a JSON-encoded string, not a dict."""
    manager = ConnectionManager()
    ws = _make_websocket()
    await manager.connect(ws, "exp-1")

    message = {"event": "results_update", "count": 42}
    await manager.broadcast("exp-1", message)

    call_args = ws.send_text.call_args[0][0]
    assert isinstance(call_args, str)
    parsed = json.loads(call_args)
    assert parsed == message


@pytest.mark.asyncio
async def test_broadcast_only_sends_to_correct_experiment():
    """broadcast() only sends to subscribers of the specified experiment."""
    manager = ConnectionManager()
    ws1 = _make_websocket()
    ws2 = _make_websocket()
    await manager.connect(ws1, "exp-1")
    await manager.connect(ws2, "exp-2")

    await manager.broadcast("exp-1", {"event": "test"})

    ws1.send_text.assert_called_once()
    ws2.send_text.assert_not_called()


# ---------------------------------------------------------------------------
# subscriber_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscriber_count_zero_for_unknown_experiment():
    """subscriber_count() returns 0 for experiments with no connections."""
    manager = ConnectionManager()
    assert manager.subscriber_count("exp-unknown") == 0


@pytest.mark.asyncio
async def test_subscriber_count_increments_on_connect():
    """subscriber_count() reflects all connected WebSockets."""
    manager = ConnectionManager()
    for i in range(5):
        ws = _make_websocket()
        await manager.connect(ws, "exp-1")
    assert manager.subscriber_count("exp-1") == 5


# ---------------------------------------------------------------------------
# active_experiments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_experiments_empty_initially():
    """active_experiments is empty when no connections exist."""
    manager = ConnectionManager()
    assert manager.active_experiments == []


@pytest.mark.asyncio
async def test_active_experiments_includes_connected_experiments():
    """active_experiments includes all experiments with at least one subscriber."""
    manager = ConnectionManager()
    ws1 = _make_websocket()
    ws2 = _make_websocket()
    await manager.connect(ws1, "exp-1")
    await manager.connect(ws2, "exp-2")

    active = manager.active_experiments
    assert "exp-1" in active
    assert "exp-2" in active
    assert len(active) == 2


@pytest.mark.asyncio
async def test_active_experiments_excludes_disconnected():
    """active_experiments does not include experiments where all subscribers left."""
    manager = ConnectionManager()
    ws = _make_websocket()
    await manager.connect(ws, "exp-1")
    await manager.disconnect(ws, "exp-1")

    assert "exp-1" not in manager.active_experiments


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_connects_are_thread_safe():
    """Multiple concurrent connect() calls don't corrupt state."""
    manager = ConnectionManager()
    websockets = [_make_websocket() for _ in range(20)]

    async def connect_all():
        tasks = [manager.connect(ws, "exp-concurrent") for ws in websockets]
        await asyncio.gather(*tasks)

    await connect_all()
    assert manager.subscriber_count("exp-concurrent") == 20


@pytest.mark.asyncio
async def test_concurrent_broadcasts_dont_crash():
    """Multiple concurrent broadcast() calls don't raise."""
    manager = ConnectionManager()
    for _ in range(5):
        ws = _make_websocket()
        await manager.connect(ws, "exp-concurrent")

    async def broadcast_many():
        tasks = [
            manager.broadcast("exp-concurrent", {"event": "test", "n": i})
            for i in range(10)
        ]
        await asyncio.gather(*tasks)

    # Should not raise
    await broadcast_many()

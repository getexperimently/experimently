# EP-058: Real-time WebSocket Streaming Results

Live experiment results delivered over WebSocket — no polling required.

## Overview

EP-058 adds a WebSocket endpoint that streams experiment result snapshots to
connected clients. The frontend uses the `useExperimentStream` hook and the
`LiveResultsPanel` component to display live data in the results dashboard.

## Architecture

```
Browser (LiveResultsPanel)
    |
    | WebSocket ws://host/api/v1/ws/experiments/{id}/results
    |
ConnectionManager  ←──── broadcasts to all subscribers of this experiment
    |
ResultsStreamingService
    |
    | Queries assignments + events tables
    |
PostgreSQL (Aurora)
```

## Backend

### WebSocket Endpoint

```
ws://localhost:8000/api/v1/ws/experiments/{experiment_id}/results
```

On connect the server sends an initial snapshot. Periodic updates are sent every
30 seconds (configurable via `RESULTS_STREAM_INTERVAL_SECONDS`).

### Client Message Protocol

| Client sends                  | Server responds                |
|-------------------------------|--------------------------------|
| `{"action": "ping"}`          | `{"event": "pong"}`            |
| `{"action": "refresh"}`       | Fresh snapshot (same shape)    |
| Any unknown action            | Ignored (no crash)             |

### Snapshot Schema

```json
{
  "event": "results_update",
  "experiment_id": "uuid-string",
  "timestamp": "2026-03-07T12:00:00+00:00",
  "status": "active",
  "variants": [
    {
      "key": "control",
      "name": "Control",
      "participant_count": 500,
      "conversion_count": 50,
      "conversion_rate": 0.10,
      "relative_lift": 0.0,
      "p_value": null,
      "is_control": true
    },
    {
      "key": "variant_b",
      "name": "Variant B",
      "participant_count": 500,
      "conversion_count": 65,
      "conversion_rate": 0.13,
      "relative_lift": 0.30,
      "p_value": 0.031,
      "is_control": false
    }
  ],
  "total_participants": 1000,
  "days_running": 7,
  "is_significant": true
}
```

### HTTP Companion Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ws/experiments/{id}/results/subscribers` | Active subscriber count |
| `GET` | `/api/v1/ws/active-experiments` | All experiments with active subscribers |

### Key Classes

**`ConnectionManager`** (`backend/app/services/websocket_manager.py`):
- Thread-safe `asyncio.Lock`-protected subscriber registry
- `connect(ws, experiment_id)` — accept and register
- `disconnect(ws, experiment_id)` — deregister; cleans up empty experiment keys
- `broadcast(experiment_id, message)` — sends to all; removes dead connections

**`ResultsStreamingService`** (`backend/app/services/results_streaming_service.py`):
- `get_live_snapshot(experiment_id)` — queries DB, returns snapshot dict
- Uses a `db_session_factory` callable for fresh sessions per snapshot
- Gracefully handles missing experiments and DB errors (returns error snapshot)
- `compute_and_broadcast(manager, experiment_id)` — convenience wrapper

### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RESULTS_STREAM_INTERVAL_SECONDS` | `30` | Periodic update interval |

## Frontend

### `useExperimentStream` Hook

```typescript
import { useExperimentStream } from '@/hooks/useExperimentStream';

function MyComponent({ experimentId }: { experimentId: string }) {
  const { snapshot, status, error, refresh, disconnect } =
    useExperimentStream(experimentId);

  // status: 'connecting' | 'connected' | 'disconnected' | 'error'
  // snapshot: ExperimentSnapshot | null
}
```

The hook auto-connects when `experimentId` is set and auto-reconnects up to 5
times (configurable) on unexpected disconnection.

WebSocket URL: `NEXT_PUBLIC_WS_URL` env var (default: `ws://localhost:8000`).

### `LiveResultsPanel` Component

```tsx
import { LiveResultsPanel } from '@/components/experiments/LiveResultsPanel';

<LiveResultsPanel experimentId="exp-uuid" />
```

Features:
- Connection status badge (green/yellow/grey/red dot)
- Pulsing "LIVE" indicator when connected
- Variant results table: Name | Participants | Conversions | Rate | Lift | P-value | Status
- Refresh button
- Last updated timestamp
- Auto-reconnect countdown when disconnected
- Error banner with reconnect button

### Results Dashboard Integration

The `LiveResultsPanel` is accessible via the **⚡ Live** tab in the
`ResultsDashboard` component on the `/results/[id]` page.

## Tests

### Running

```bash
source venv/bin/activate
export APP_ENV=test TESTING=true

# Unit tests
python -m pytest backend/tests/unit/services/test_websocket_manager.py -v
python -m pytest backend/tests/unit/services/test_results_streaming_service.py -v

# Integration tests
python -m pytest backend/tests/integration/api/test_websocket_results.py -v

# All together
python -m pytest \
  backend/tests/unit/services/test_websocket_manager.py \
  backend/tests/unit/services/test_results_streaming_service.py \
  backend/tests/integration/api/test_websocket_results.py \
  -v --tb=short
```

### Test Coverage

| Test file | Tests | Covers |
|-----------|-------|--------|
| `test_websocket_manager.py` | 22 | ConnectionManager lifecycle, broadcast, concurrency |
| `test_results_streaming_service.py` | 23 | Snapshot schema, DB error handling, significance logic |
| `test_websocket_results.py` | 34 | WebSocket protocol, HTTP endpoints, edge cases |
| **Total** | **79** | |

All tests mock the DB session; no live PostgreSQL required.

## Authentication

The stream requires the same credentials as the HTTP API. The token is validated
before the socket is registered; a missing or invalid token is answered with an
accepted-then-closed socket, close code **4401**, so browser clients can tell
"unauthorized" from a network failure and must not reconnect with the same token.

Ways to present the token, in order of preference:

1. **Subprotocol** (what the dashboard uses):
   `new WebSocket(url, ['experimently.bearer', token])`. The server echoes
   `experimently.bearer` as the accepted subprotocol. This keeps the token out of
   URLs and therefore out of access logs.
2. **`Authorization: Bearer <token>` header** for non-browser clients.
3. **`?token=<token>` query parameter**, supported for compatibility only. URLs are
   written to proxy and server access logs, so prefer 1 or 2.

`frontend/src/hooks/useExperimentStream.ts` stops reconnecting and reports
`status: 'unauthorized'` on close code 4401.

The HTTP companion endpoints (subscriber counts, active experiments) are read-only
and informational.

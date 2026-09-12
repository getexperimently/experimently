/**
 * useExperimentStream — EP-058: Real-time WebSocket Streaming Results
 *
 * Custom React hook that manages a WebSocket connection to the experiment
 * results streaming endpoint. Handles connection lifecycle, auto-reconnect,
 * and client-to-server message actions (ping, refresh).
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { getToken, wsBase } from '@/services/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface VariantResult {
  key: string;
  name: string;
  participantCount: number;
  conversionCount: number;
  conversionRate: number;
  relativeLift: number;
  pValue: number | null;
  isControl: boolean;
}

export interface ExperimentSnapshot {
  event: string;
  experimentId: string;
  timestamp: string;
  status: 'active' | 'paused' | 'completed' | 'draft' | 'not_found' | 'error';
  variants: VariantResult[];
  totalParticipants: number;
  daysRunning: number | null;
  isSignificant: boolean;
  error?: string;
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error' | 'unauthorized';

/** Subprotocol marker that precedes the bearer token in the handshake. */
export const WS_AUTH_SUBPROTOCOL = 'experimently.bearer';

/** Application close code the backend uses for a missing/invalid token. */
export const WS_CLOSE_UNAUTHORIZED = 4401;

/** Close codes after which reconnecting cannot help. */
const TERMINAL_CLOSE_CODES = new Set([WS_CLOSE_UNAUTHORIZED, 4403, 1008]);

export interface UseExperimentStreamOptions {
  /** Whether to auto-connect when experimentId is set. Default: true */
  autoConnect?: boolean;
  /** Delay in ms before reconnecting after a disconnect. Default: 3000 */
  reconnectDelayMs?: number;
  /** Maximum number of reconnect attempts before giving up. Default: 5 */
  maxReconnectAttempts?: number;
}

export interface UseExperimentStreamResult {
  snapshot: ExperimentSnapshot | null;
  status: ConnectionStatus;
  error: string | null;
  connect: () => void;
  disconnect: () => void;
  refresh: () => void;
  ping: () => void;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

/**
 * Convert snake_case server fields to camelCase VariantResult.
 * The server sends snake_case JSON; we normalise here so consumers see
 * camelCase consistently.
 */
function parseVariant(raw: Record<string, unknown>): VariantResult {
  return {
    key: String(raw.key ?? ''),
    name: String(raw.name ?? ''),
    participantCount: Number(raw.participant_count ?? 0),
    conversionCount: Number(raw.conversion_count ?? 0),
    conversionRate: Number(raw.conversion_rate ?? 0),
    relativeLift: Number(raw.relative_lift ?? 0),
    pValue: raw.p_value != null ? Number(raw.p_value) : null,
    isControl: Boolean(raw.is_control),
  };
}

function parseSnapshot(raw: Record<string, unknown>): ExperimentSnapshot {
  const rawVariants = Array.isArray(raw.variants) ? raw.variants : [];
  return {
    event: String(raw.event ?? 'results_update'),
    experimentId: String(raw.experiment_id ?? ''),
    timestamp: String(raw.timestamp ?? ''),
    status: (raw.status as ExperimentSnapshot['status']) ?? 'error',
    variants: rawVariants.map((v) => parseVariant(v as Record<string, unknown>)),
    totalParticipants: Number(raw.total_participants ?? 0),
    daysRunning: raw.days_running != null ? Number(raw.days_running) : null,
    isSignificant: Boolean(raw.is_significant),
    error: raw.error != null ? String(raw.error) : undefined,
  };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Build the streaming URL. The origin comes from `NEXT_PUBLIC_WS_URL`,
 * `NEXT_PUBLIC_API_URL` or, for same-origin deployments, `window.location`.
 * The token is never put in the URL (URLs end up in access logs); see
 * `buildStreamProtocols`.
 */
export function buildStreamUrl(experimentId: string): string {
  return `${wsBase()}/api/v1/ws/experiments/${encodeURIComponent(experimentId)}/results`;
}

/**
 * Browsers cannot set headers on a WebSocket handshake, but they can offer
 * subprotocols. The token rides as `Sec-WebSocket-Protocol: experimently.bearer, <token>`
 * and the backend echoes `experimently.bearer` on accept. Returns `undefined`
 * when there is no token so the socket is opened without a protocol list.
 */
export function buildStreamProtocols(): string[] | undefined {
  const token = getToken();
  return token ? [WS_AUTH_SUBPROTOCOL, token] : undefined;
}

export function useExperimentStream(
  experimentId: string | null,
  options?: UseExperimentStreamOptions,
): UseExperimentStreamResult {
  const {
    autoConnect = true,
    reconnectDelayMs = 3000,
    maxReconnectAttempts = 5,
  } = options ?? {};

  const [snapshot, setSnapshot] = useState<ExperimentSnapshot | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCount = useRef<number>(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalDisconnect = useRef<boolean>(false);

  // ------------------------------------------------------------------
  // connect
  // ------------------------------------------------------------------

  const connect = useCallback(() => {
    if (!experimentId) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    const url = buildStreamUrl(experimentId);
    setStatus('connecting');
    setError(null);
    intentionalDisconnect.current = false;

    try {
      const protocols = buildStreamProtocols();
      const ws = protocols ? new WebSocket(url, protocols) : new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectCount.current = 0;
        setStatus('connected');
        setError(null);
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const raw = JSON.parse(event.data as string) as Record<string, unknown>;
          const parsed = parseSnapshot(raw);
          setSnapshot(parsed);
        } catch (parseError) {
          console.warn('[useExperimentStream] Failed to parse message:', parseError);
        }
      };

      ws.onerror = () => {
        setStatus('error');
        setError('WebSocket connection error');
      };

      ws.onclose = (event?: CloseEvent) => {
        wsRef.current = null;

        if (intentionalDisconnect.current) {
          setStatus('disconnected');
          return;
        }

        // The backend accepts and then closes with 4401 when the token is
        // missing, expired or invalid. Reconnecting with the same token can
        // only loop, so stop and surface it.
        const code = event?.code;
        if (code !== undefined && TERMINAL_CLOSE_CODES.has(code)) {
          setStatus('unauthorized');
          setError(
            code === WS_CLOSE_UNAUTHORIZED
              ? 'Not authorized to stream results; sign in again.'
              : `Connection refused by the server (code ${code})`,
          );
          return;
        }

        // Attempt reconnect
        if (reconnectCount.current < maxReconnectAttempts) {
          reconnectCount.current += 1;
          setStatus('connecting');
          reconnectTimerRef.current = setTimeout(() => {
            connect();
          }, reconnectDelayMs);
        } else {
          setStatus('disconnected');
          setError(`Lost connection after ${maxReconnectAttempts} reconnect attempts`);
        }
      };
    } catch (err) {
      setStatus('error');
      setError(String(err));
    }
  }, [experimentId, reconnectDelayMs, maxReconnectAttempts]);

  // ------------------------------------------------------------------
  // disconnect
  // ------------------------------------------------------------------

  const disconnect = useCallback(() => {
    intentionalDisconnect.current = true;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus('disconnected');
  }, []);

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  const refresh = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'refresh' }));
    }
  }, []);

  const ping = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'ping' }));
    }
  }, []);

  // ------------------------------------------------------------------
  // Lifecycle
  // ------------------------------------------------------------------

  useEffect(() => {
    if (!experimentId || autoConnect === false) return;
    connect();
    return () => {
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [experimentId]);

  return { snapshot, status, error, connect, disconnect, refresh, ping };
}

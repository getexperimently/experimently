import { renderHook, act } from '@testing-library/react';
import { useExperimentStream } from '@/hooks/useExperimentStream';

// Mock WebSocket
class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;

  url: string;
  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sentMessages: string[] = [];
  closeCalled = false;

  constructor(url: string) {
    this.url = url;
    // Simulate async open
    setTimeout(() => this.onopen?.(), 0);
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close() {
    this.closeCalled = true;
    this.readyState = MockWebSocket.CLOSED;
    setTimeout(() => this.onclose?.(), 0);
  }
}

let wsInstances: MockWebSocket[] = [];

beforeEach(() => {
  wsInstances = [];
  (global as unknown as Record<string, unknown>).WebSocket = class extends MockWebSocket {
    constructor(url: string) {
      super(url);
      wsInstances.push(this);
    }
  };
  // Set static properties on the mock constructor
  (global as unknown as Record<string, unknown>).WebSocket = Object.assign(
    (global as unknown as Record<string, typeof MockWebSocket>).WebSocket,
    { OPEN: 1, CLOSED: 3 },
  );
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('useExperimentStream', () => {
  it('returns disconnected status initially with no experimentId', () => {
    const { result } = renderHook(() => useExperimentStream(null));
    expect(result.current.status).toBe('disconnected');
    expect(result.current.snapshot).toBeNull();
  });

  it('auto-connects when experimentId is provided', async () => {
    const { result } = renderHook(() => useExperimentStream('exp-1'));
    expect(result.current.status).toBe('connecting');
    expect(wsInstances.length).toBe(1);
    expect(wsInstances[0].url).toContain('/api/v1/ws/experiments/exp-1/results');

    // Simulate open
    await act(async () => {
      wsInstances[0].onopen?.();
    });
    expect(result.current.status).toBe('connected');
  });

  it('does not auto-connect when autoConnect is false', () => {
    renderHook(() => useExperimentStream('exp-1', { autoConnect: false }));
    expect(wsInstances.length).toBe(0);
  });

  it('parses snapshot from message', async () => {
    const { result } = renderHook(() => useExperimentStream('exp-1'));

    await act(async () => {
      wsInstances[0].onopen?.();
    });

    const raw = {
      event: 'results_update',
      experiment_id: 'exp-1',
      timestamp: '2024-06-01T00:00:00Z',
      status: 'active',
      variants: [
        {
          key: 'control',
          name: 'Control',
          participant_count: 500,
          conversion_count: 50,
          conversion_rate: 0.1,
          relative_lift: 0,
          p_value: null,
          is_control: true,
        },
      ],
      total_participants: 500,
      days_running: 3,
      is_significant: false,
    };

    await act(async () => {
      wsInstances[0].onmessage?.({ data: JSON.stringify(raw) });
    });

    expect(result.current.snapshot).not.toBeNull();
    expect(result.current.snapshot!.experimentId).toBe('exp-1');
    expect(result.current.snapshot!.totalParticipants).toBe(500);
    expect(result.current.snapshot!.variants[0].participantCount).toBe(500);
    expect(result.current.snapshot!.variants[0].isControl).toBe(true);
  });

  it('sends refresh action', async () => {
    const { result } = renderHook(() => useExperimentStream('exp-1'));

    await act(async () => { wsInstances[0].onopen?.(); });
    act(() => { result.current.refresh(); });

    expect(wsInstances[0].sentMessages).toContain(JSON.stringify({ action: 'refresh' }));
  });

  it('sends ping action', async () => {
    const { result } = renderHook(() => useExperimentStream('exp-1'));

    await act(async () => { wsInstances[0].onopen?.(); });
    act(() => { result.current.ping(); });

    expect(wsInstances[0].sentMessages).toContain(JSON.stringify({ action: 'ping' }));
  });

  it('disconnect sets status to disconnected', async () => {
    const { result } = renderHook(() => useExperimentStream('exp-1'));

    await act(async () => { wsInstances[0].onopen?.(); });
    expect(result.current.status).toBe('connected');

    await act(async () => { result.current.disconnect(); });
    expect(result.current.status).toBe('disconnected');
  });

  it('sets error status on WebSocket error', async () => {
    const { result } = renderHook(() => useExperimentStream('exp-1'));

    await act(async () => {
      wsInstances[0].onerror?.();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('WebSocket connection error');
  });

  it('manual connect works after autoConnect false', async () => {
    const { result } = renderHook(() =>
      useExperimentStream('exp-1', { autoConnect: false }),
    );

    expect(wsInstances.length).toBe(0);
    act(() => { result.current.connect(); });
    expect(wsInstances.length).toBe(1);
  });

  it('handles malformed message gracefully', async () => {
    const spy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    const { result } = renderHook(() => useExperimentStream('exp-1'));

    await act(async () => { wsInstances[0].onopen?.(); });
    await act(async () => {
      wsInstances[0].onmessage?.({ data: 'not-json' });
    });

    expect(result.current.snapshot).toBeNull();
    spy.mockRestore();
  });

  it('cleans up on unmount', async () => {
    const { unmount } = renderHook(() => useExperimentStream('exp-1'));

    await act(async () => { wsInstances[0].onopen?.(); });
    unmount();

    expect(wsInstances[0].closeCalled).toBe(true);
  });

  it('does not connect with null experimentId via manual connect', () => {
    const { result } = renderHook(() => useExperimentStream(null));
    act(() => { result.current.connect(); });
    expect(wsInstances.length).toBe(0);
  });
});

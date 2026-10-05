import { useCallback, useEffect, useRef, useState } from 'react';
import { Segment, SegmentsService } from '@/services/segments';

export type SegmentListState = 'idle' | 'loading' | 'ready' | 'error';

export interface SegmentList {
  state: SegmentListState;
  /** Every segment, any status, once `state` is `ready`. */
  segments: Segment[];
  retry: () => void;
}

/**
 * Every segment, loaded once `enabled` turns true (a rule builder turns it on
 * when a condition uses a segment operator, so a page without one makes no
 * request). A failure leaves `state: 'error'` until `retry`.
 */
export function useSegmentList(enabled: boolean): SegmentList {
  const [state, setState] = useState<SegmentListState>('idle');
  const [segments, setSegments] = useState<Segment[]>([]);
  const [attempt, setAttempt] = useState(0);
  // The attempt whose list arrived: turning `enabled` off and on again does not reload it.
  const loadedFor = useRef(-1);

  useEffect(() => {
    if (!enabled || loadedFor.current === attempt) return;
    let live = true;
    setState('loading');
    SegmentsService.listAll()
      .then((items) => {
        if (!live) return;
        loadedFor.current = attempt;
        setSegments(items);
        setState('ready');
      })
      .catch(() => {
        if (live) setState('error');
      });
    return () => {
      live = false;
    };
  }, [enabled, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, segments, retry };
}

/**
 * Warn before a reload or a closed tab throws away unsaved answers.
 *
 * Only the browser's own `beforeunload` prompt: moving between steps, switching
 * to the single-page form and the redirect after a successful create are all
 * in-app navigations and never ask. (A prompt for in-app links is separate
 * work.)
 */
import { MutableRefObject, useEffect } from 'react';

/**
 * While `dirty`, ask before the page unloads — unless `armedRef.current` is
 * false. The ref, not state, is what disarms it: the page clears it
 * synchronously just before it navigates away after a successful create, so a
 * full-page fallback navigation that happens before React re-renders is never
 * held up by a prompt for work that has in fact been saved.
 */
export function useLeaveGuard(dirty: boolean, armedRef: MutableRefObject<boolean>): void {
  useEffect(() => {
    if (!dirty) return undefined;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!armedRef.current) return;
      event.preventDefault();
      // Older browsers show the prompt only when returnValue is set.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [dirty, armedRef]);
}

/**
 * A full-page navigation. Used only when the in-app route change after a
 * successful create fails, so the user still lands on the new experiment.
 * Its own function so tests can stand in for the browser.
 */
export function navigateHard(url: string): void {
  window.location.assign(url);
}

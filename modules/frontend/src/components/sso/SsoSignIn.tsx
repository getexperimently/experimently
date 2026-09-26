/**
 * The "Sign in with SSO" part of `/login` (C2b).
 *
 * Shown only when `GET /api/v1/modules` lists `sso`. It also reads
 * `/login?sso_error=...` — whether or not the modules answer has arrived — and
 * hands the copy to the login page's own alert through `onError`, opens the
 * form, and removes the four parameters from the address bar once rendered.
 */
import React, { FormEvent, useCallback, useEffect, useId, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import { useModule } from '@/contexts/ModulesContext';
import { MODULES } from '@/services/modules';
import {
  SSO_ERROR_PARAMS,
  clearPending,
  readPending,
  readSsoErrorParams,
  ssoErrorMessage,
  startSsoSignIn,
} from '@modules/services/sso';

export interface SsoSignInProps {
  /** Where to go after signing in (already `safeNextPath`-checked). */
  nextPath: string;
  /** Put an SSO error in the login page's alert; `retry` re-opens the form. */
  onError: (message: string | null, retry: (() => void) | null) => void;
  /** C1b's copy for a 429 and for an unreachable API. */
  rateLimitedMessage: string;
  unreachableMessage: () => string;
}

export default function SsoSignIn({
  nextPath,
  onError,
  rateLimitedMessage,
  unreachableMessage,
}: SsoSignInProps) {
  const router = useRouter();
  const installed = useModule(MODULES.SSO);
  const emailId = useId();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [starting, setStarting] = useState(false);
  const [next, setNext] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const handled = useRef(false);

  const reopen = useCallback(() => {
    setOpen(true);
    // After the form has rendered.
    setTimeout(() => emailRef.current?.focus(), 0);
  }, []);

  // /login?sso_error=...: the copy, the form open, then a clean address bar.
  useEffect(() => {
    if (handled.current || !router.isReady) return;
    const params = readSsoErrorParams(router.query);
    if (!params) return;
    handled.current = true;
    const pending = readPending();
    clearPending();
    if (pending?.next) setNext(pending.next);
    onError(
      ssoErrorMessage(params, {
        domain: pending?.domain,
        rateLimited: rateLimitedMessage,
        unreachable: unreachableMessage(),
      }),
      reopen,
    );
    reopen();
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      if (SSO_ERROR_PARAMS.some((p) => url.searchParams.has(p))) {
        window.history.replaceState(window.history.state, '', '/login');
      }
    }
  }, [router.isReady, router.query, onError, reopen, rateLimitedMessage, unreachableMessage]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (starting) return;
    setStarting(true);
    onError(null, null);
    try {
      await startSsoSignIn(email, next ?? nextPath);
    } catch (err) {
      setStarting(false);
      onError(err instanceof Error ? err.message : 'Sign-in could not start.', reopen);
    }
  };

  if (!installed) return null;

  return (
    <div className="mt-5 border-t border-slate-200 pt-5" data-testid="sso-section">
      {!open ? (
        <button
          type="button"
          data-testid="sso-open"
          onClick={reopen}
          className="w-full inline-flex items-center justify-center px-4 py-2 border border-slate-300 text-slate-800 text-sm font-medium rounded-md hover:bg-slate-50 transition-colors"
        >
          Sign in with SSO
        </button>
      ) : (
        <form onSubmit={handleSubmit} noValidate data-testid="sso-form">
          <label htmlFor={emailId} className="block text-sm font-medium text-slate-700 mb-1">
            Work email
          </label>
          <input
            ref={emailRef}
            id={emailId}
            name="sso-email"
            type="email"
            autoComplete="email"
            required
            readOnly={starting}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@yourcompany.com"
            data-testid="sso-email"
            className="w-full px-3 py-2 mb-3 border border-slate-300 rounded-md text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 read-only:bg-slate-50"
          />
          <button
            type="submit"
            data-testid="sso-submit"
            disabled={starting}
            aria-busy={starting}
            className="w-full inline-flex items-center justify-center px-4 py-2 border border-slate-300 text-slate-800 text-sm font-medium rounded-md hover:bg-slate-50 disabled:opacity-60 transition-colors"
          >
            {starting ? 'Redirecting…' : 'Continue with SSO'}
          </button>
        </form>
      )}
    </div>
  );
}

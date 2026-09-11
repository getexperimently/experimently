/**
 * Anonymous visitor identity for the storefront.
 *
 * The id lives in localStorage under `shoplab.visitor_id` so the same browser keeps the
 * same experiment assignments across reloads. Everything here is safe to import on the
 * server: functions return `null` when there is no `window`.
 */

export const VISITOR_ID_KEY = 'shoplab.visitor_id';
export const VISITOR_FIRST_SEEN_KEY = 'shoplab.visitor_first_seen';

export type Device = 'desktop' | 'mobile' | 'tablet';

export interface VisitorAttributes extends Record<string, unknown> {
  device: Device;
  country: string;
  returning: boolean;
}

export interface Visitor {
  id: string;
  attributes: VisitorAttributes;
}

export function isBrowser(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isUuidV4(value: unknown): value is string {
  return typeof value === 'string' && UUID_V4.test(value);
}

/** UUID v4 via `crypto.randomUUID()`, with a `getRandomValues` fallback for older engines. */
export function generateVisitorId(): string {
  const c: Crypto | undefined = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && typeof c.randomUUID === 'function') {
    return c.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') {
    c.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Classify the device from a user-agent string and viewport width. Pure. */
export function detectDevice(userAgent: string, viewportWidth: number): Device {
  const ua = userAgent.toLowerCase();
  if (/ipad|tablet|kindle|silk|playbook/.test(ua) || (/android/.test(ua) && !/mobile/.test(ua))) {
    return 'tablet';
  }
  if (/iphone|ipod|android.*mobile|windows phone|blackberry|opera mini|mobile/.test(ua)) {
    return 'mobile';
  }
  if (viewportWidth > 0 && viewportWidth < 640) return 'mobile';
  if (viewportWidth > 0 && viewportWidth < 1024) return 'tablet';
  return 'desktop';
}

/** Derive a two-letter country code from a BCP-47 locale (`en-GB` → `GB`). Pure. */
export function countryFromLocale(locale: string | undefined): string {
  if (!locale) return 'US';
  const parts = locale.replace('_', '-').split('-');
  const region = parts.find((p, i) => i > 0 && /^[A-Za-z]{2}$/.test(p));
  return region ? region.toUpperCase() : 'US';
}

function readAttributes(returning: boolean): VisitorAttributes {
  if (!isBrowser()) {
    return { device: 'desktop', country: 'US', returning };
  }
  return {
    device: detectDevice(window.navigator.userAgent || '', window.innerWidth || 0),
    country: countryFromLocale(window.navigator.language),
    returning,
  };
}

/** Read the current visitor without creating one. `null` on the server or when absent. */
export function getVisitor(): Visitor | null {
  if (!isBrowser()) return null;
  try {
    const id = window.localStorage.getItem(VISITOR_ID_KEY);
    if (!isUuidV4(id)) return null;
    return { id, attributes: readAttributes(true) };
  } catch {
    return null;
  }
}

/**
 * Return the stored visitor, creating one on first visit. A visitor is `returning`
 * when the id already existed in this browser before this call.
 */
export function getOrCreateVisitor(): Visitor | null {
  if (!isBrowser()) return null;
  const existing = getVisitor();
  if (existing) return existing;
  const id = generateVisitorId();
  try {
    window.localStorage.setItem(VISITOR_ID_KEY, id);
    window.localStorage.setItem(VISITOR_FIRST_SEEN_KEY, new Date().toISOString());
  } catch {
    // Private mode / quota errors: fall through with an in-memory id.
  }
  return { id, attributes: readAttributes(false) };
}

/** Throw away the current visitor and mint a fresh id (used by the panel's "New visitor"). */
export function resetVisitor(): Visitor | null {
  if (!isBrowser()) return null;
  try {
    window.localStorage.removeItem(VISITOR_ID_KEY);
    window.localStorage.removeItem(VISITOR_FIRST_SEEN_KEY);
  } catch {
    // ignore
  }
  return getOrCreateVisitor();
}

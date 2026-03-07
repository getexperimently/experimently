/**
 * Map-based in-memory cache with TTL support.
 *
 * Designed for edge runtimes where:
 * - Worker instances are short-lived (1-30 seconds)
 * - No shared memory between worker instances
 * - No Node.js built-ins are available
 *
 * The cache uses a simple Map and relies on wall-clock time for expiry.
 * Entries are lazily evicted on read (no background timers needed).
 */

import type { CacheEntry } from './types';

export class EdgeCache<T> {
  private readonly store = new Map<string, CacheEntry<T>>();
  private readonly ttlMs: number;

  constructor(ttlMs: number) {
    this.ttlMs = ttlMs;
  }

  /**
   * Retrieve a cached value.
   * Returns `undefined` when the entry is missing or has expired.
   */
  get(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) return undefined;

    if (Date.now() > entry.expiresAt) {
      this.store.delete(key); // lazy eviction
      return undefined;
    }

    return entry.value;
  }

  /**
   * Store a value with the configured TTL.
   */
  set(key: string, value: T): void {
    this.store.set(key, { value, expiresAt: Date.now() + this.ttlMs });
  }

  /**
   * Store a value with an explicit TTL (overrides the instance default).
   */
  setWithTtl(key: string, value: T, ttlMs: number): void {
    this.store.set(key, { value, expiresAt: Date.now() + ttlMs });
  }

  /**
   * Remove a single entry.
   */
  delete(key: string): void {
    this.store.delete(key);
  }

  /**
   * Evict all expired entries. Call periodically to avoid memory growth
   * in long-running workers (e.g. Deno Deploy services).
   */
  evictExpired(): void {
    const now = Date.now();
    for (const [key, entry] of this.store.entries()) {
      if (now > entry.expiresAt) {
        this.store.delete(key);
      }
    }
  }

  /**
   * Remove all entries.
   */
  clear(): void {
    this.store.clear();
  }

  /**
   * Number of entries currently in the cache (including expired ones
   * that have not yet been lazily evicted).
   */
  get size(): number {
    return this.store.size;
  }
}

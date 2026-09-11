/**
 * In-memory per-user, per-key cache with TTL support for the React Native SDK.
 *
 * Entries are evicted lazily on the next access after they expire.
 * This is intentionally lightweight — AsyncStorage handles persistence.
 * Only successful server results are ever stored.
 */

import type { CacheEntry } from './types';

export class EvaluationCache<T> {
  private readonly ttlMs: number;
  private readonly users = new Map<string, Map<string, CacheEntry<T>>>();

  constructor(ttlMs: number) {
    this.ttlMs = ttlMs;
  }

  /** Returns the cached value for `userId` + `key`, or `undefined` if absent or expired. */
  get(userId: string, key: string): T | undefined {
    const byKey = this.users.get(userId);
    const entry = byKey?.get(key);
    if (!entry) return undefined;

    if (Date.now() > entry.expiresAt) {
      byKey?.delete(key);
      return undefined;
    }

    return entry.value;
  }

  /** Returns true if a non-expired entry exists. */
  has(userId: string, key: string): boolean {
    return this.get(userId, key) !== undefined;
  }

  /** Stores `value` under `userId` + `key` with the configured TTL. */
  set(userId: string, key: string, value: T): void {
    let byKey = this.users.get(userId);
    if (!byKey) {
      byKey = new Map();
      this.users.set(userId, byKey);
    }
    byKey.set(key, { value, expiresAt: Date.now() + this.ttlMs });
  }

  /** Removes the entry for `userId` + `key`. */
  delete(userId: string, key: string): void {
    this.users.get(userId)?.delete(key);
  }

  /** All live (non-expired) entries for a user, in insertion order. */
  entries(userId: string): Array<[string, T]> {
    const byKey = this.users.get(userId);
    if (!byKey) return [];
    const now = Date.now();
    const live: Array<[string, T]> = [];
    for (const [key, entry] of byKey) {
      if (now > entry.expiresAt) byKey.delete(key);
      else live.push([key, entry.value]);
    }
    return live;
  }

  /** Removes all entries. */
  clear(): void {
    this.users.clear();
  }

  /** Number of entries across all users (including expired ones not yet evicted). */
  get size(): number {
    let total = 0;
    for (const byKey of this.users.values()) total += byKey.size;
    return total;
  }
}

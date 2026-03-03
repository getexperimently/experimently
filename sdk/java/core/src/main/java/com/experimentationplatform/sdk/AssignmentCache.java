package com.experimentationplatform.sdk;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Thread-safe in-memory LRU cache with TTL (time-to-live) eviction for assignment results.
 *
 * <p>When the cache reaches {@code maxSize} entries, the least-recently-accessed entry is
 * automatically evicted (LRU eviction via {@link LinkedHashMap} in access-order mode).
 * Entries also expire after {@code ttlMs} milliseconds from insertion regardless of access
 * patterns (TTL eviction checked on each {@link #get(String)}).
 *
 * <p>All public methods are {@code synchronized} for thread safety.
 *
 * <h2>Usage</h2>
 * <pre>
 *     AssignmentCache cache = new AssignmentCache(1000, 300_000L); // 1000 entries, 5 min TTL
 *     cache.put("user-123:my-flag", "on");
 *     String result = cache.get("user-123:my-flag"); // "on" (if not expired)
 * </pre>
 */
public class AssignmentCache {

    private final int maxSize;
    private final long ttlMs;
    private final Map<String, CacheEntry> cache;

    /**
     * Creates a new AssignmentCache.
     *
     * @param maxSize maximum number of entries before LRU eviction kicks in (must be >= 1)
     * @param ttlMs   time-to-live for entries in milliseconds (must be > 0)
     * @throws IllegalArgumentException if maxSize <= 0 or ttlMs <= 0
     */
    public AssignmentCache(int maxSize, long ttlMs) {
        if (maxSize <= 0) throw new IllegalArgumentException("maxSize must be positive");
        if (ttlMs <= 0) throw new IllegalArgumentException("ttlMs must be positive");
        this.maxSize = maxSize;
        this.ttlMs = ttlMs;
        // accessOrder=true enables LRU eviction via removeEldestEntry
        this.cache = new LinkedHashMap<String, CacheEntry>(maxSize, 0.75f, true) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<String, CacheEntry> eldest) {
                return size() > maxSize;
            }
        };
    }

    /**
     * Stores a value in the cache with the current timestamp as the base for TTL.
     *
     * @param key   cache key (typically "{userId}:{flagKey}")
     * @param value the value to cache (non-null)
     */
    public synchronized void put(String key, String value) {
        cache.put(key, new CacheEntry(value, System.currentTimeMillis() + ttlMs));
    }

    /**
     * Retrieves a cached value for the given key.
     *
     * <p>Returns {@code null} if:
     * <ul>
     *   <li>The key is not present in the cache, or</li>
     *   <li>The entry has expired (current time > insertion time + TTL).</li>
     * </ul>
     * Expired entries are removed lazily on access.
     *
     * @param key cache key
     * @return the cached value, or {@code null} if absent or expired
     */
    public synchronized String get(String key) {
        CacheEntry entry = cache.get(key);
        if (entry == null) {
            return null;
        }
        if (System.currentTimeMillis() > entry.expiresAt) {
            cache.remove(key);
            return null;
        }
        return entry.value;
    }

    /**
     * Removes a specific key from the cache.
     *
     * @param key the key to invalidate
     */
    public synchronized void invalidate(String key) {
        cache.remove(key);
    }

    /**
     * Returns the current number of entries in the cache (including potentially expired ones
     * that have not yet been lazily evicted).
     *
     * @return current cache size
     */
    public synchronized int size() {
        return cache.size();
    }

    /**
     * Removes all entries from the cache.
     */
    public synchronized void clear() {
        cache.clear();
    }

    /**
     * Returns the maximum number of entries this cache can hold before LRU eviction.
     *
     * @return maximum cache size
     */
    public int getMaxSize() {
        return maxSize;
    }

    /**
     * Returns the TTL for cache entries in milliseconds.
     *
     * @return TTL in milliseconds
     */
    public long getTtlMs() {
        return ttlMs;
    }

    /**
     * Internal cache entry holding a value and its expiration timestamp.
     */
    private static class CacheEntry {
        final String value;
        final long expiresAt; // absolute epoch millis

        CacheEntry(String value, long expiresAt) {
            this.value = value;
            this.expiresAt = expiresAt;
        }
    }
}

package com.experimentationplatform.android

import java.util.concurrent.locks.ReentrantReadWriteLock
import kotlin.concurrent.read
import kotlin.concurrent.write

/**
 * Cache entry wrapping a value with an expiry timestamp.
 */
data class CacheEntry<T>(
    val value: T,
    val expiresAt: Long  // System.currentTimeMillis() epoch ms
) {
    val isExpired: Boolean get() = System.currentTimeMillis() > expiresAt
}

/**
 * Thread-safe LRU cache with TTL support.
 *
 * Uses a LinkedHashMap in access-order mode for LRU eviction.
 * Safe for concurrent use via ReentrantReadWriteLock.
 * Does NOT depend on android.util.LruCache — works in plain JVM test environments.
 */
class FlagCache(
    private val maxSize: Int = 1000,
    private val ttlMs: Long = 300_000L
) {
    private val lock = ReentrantReadWriteLock()
    private val store = object : LinkedHashMap<String, CacheEntry<FeatureFlag>>(
        16, 0.75f, true  // accessOrder = true enables LRU
    ) {
        override fun removeEldestEntry(eldest: Map.Entry<String, CacheEntry<FeatureFlag>>): Boolean {
            return size > maxSize
        }
    }

    /**
     * Retrieves a flag from the cache.
     * Returns null if the key is absent or the entry has expired.
     */
    fun get(key: String): FeatureFlag? = lock.read {
        val entry = store[key] ?: return null
        if (entry.isExpired) null else entry.value
    }

    /**
     * Stores a flag in the cache with the configured TTL.
     */
    fun set(key: String, flag: FeatureFlag) = lock.write {
        store[key] = CacheEntry(flag, System.currentTimeMillis() + ttlMs)
    }

    /**
     * Removes a specific key from the cache.
     */
    fun remove(key: String) = lock.write { store.remove(key) }

    /**
     * Removes all entries from the cache.
     */
    fun clear() = lock.write { store.clear() }

    /**
     * Returns the current number of entries (including expired ones not yet evicted).
     */
    fun size(): Int = lock.read { store.size }

    /**
     * Returns only non-expired entries as a snapshot.
     */
    fun entries(): Map<String, FeatureFlag> = lock.read {
        store.filter { !it.value.isExpired }.mapValues { it.value.value }
    }
}

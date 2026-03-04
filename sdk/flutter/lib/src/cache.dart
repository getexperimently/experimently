/// In-memory LRU-style cache with TTL support.
library experimentation_sdk_cache;

/// A single entry in the cache.
class _CacheEntry<T> {
  final T value;
  final DateTime expiresAt;

  _CacheEntry(this.value, this.expiresAt);

  bool get isExpired => DateTime.now().isAfter(expiresAt);
}

/// Thread-safe (single-isolate) in-memory cache with per-entry TTL.
///
/// Keys are strings; values are generic. Expired entries are evicted lazily
/// on the next access.
class EvaluationCache<T> {
  final Duration ttl;
  final Map<String, _CacheEntry<T>> _store = {};

  EvaluationCache({required this.ttl});

  /// Returns the cached value for [key], or `null` if absent or expired.
  T? get(String key) {
    final entry = _store[key];
    if (entry == null) return null;
    if (entry.isExpired) {
      _store.remove(key);
      return null;
    }
    return entry.value;
  }

  /// Stores [value] under [key] with the configured [ttl].
  void set(String key, T value) {
    _store[key] = _CacheEntry(value, DateTime.now().add(ttl));
  }

  /// Removes the entry for [key] if present.
  void invalidate(String key) {
    _store.remove(key);
  }

  /// Removes all entries from the cache.
  void clear() {
    _store.clear();
  }

  /// Number of non-expired entries currently in the cache.
  int get size {
    _evictExpired();
    return _store.length;
  }

  /// Whether the cache contains a non-expired entry for [key].
  bool containsKey(String key) => get(key) != null;

  void _evictExpired() {
    _store.removeWhere((_, entry) => entry.isExpired);
  }
}

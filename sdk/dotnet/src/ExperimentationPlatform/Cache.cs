namespace ExperimentationPlatform;

/// <summary>
/// Thread-safe in-memory cache with TTL expiration and LRU-style eviction.
/// </summary>
/// <typeparam name="TValue">The type of cached values.</typeparam>
public class SdkCache<TValue>
{
    private readonly int _maxSize;
    private readonly TimeSpan _defaultTtl;

    // Dictionary preserves insertion order (guaranteed in .NET 5+).
    // We rely on this to evict the oldest entry.
    private readonly Dictionary<string, CacheEntry> _store;
    private readonly object _lock = new();

    private struct CacheEntry
    {
        public TValue Value;
        public DateTime ExpiresAt;
    }

    /// <summary>
    /// Creates a new cache.
    /// </summary>
    /// <param name="maxSize">Maximum number of entries before oldest is evicted.</param>
    /// <param name="defaultTtl">Default time-to-live for entries.</param>
    public SdkCache(int maxSize = 1000, TimeSpan? defaultTtl = null)
    {
        _maxSize = maxSize;
        _defaultTtl = defaultTtl ?? TimeSpan.FromSeconds(300);
        _store = new Dictionary<string, CacheEntry>(_maxSize);
    }

    /// <summary>Gets a cached value, or default if not found or expired.</summary>
    public TValue? Get(string key)
    {
        lock (_lock)
        {
            if (!_store.TryGetValue(key, out var entry))
                return default;

            if (DateTime.UtcNow >= entry.ExpiresAt)
            {
                _store.Remove(key);
                return default;
            }

            return entry.Value;
        }
    }

    /// <summary>Sets a value in the cache.</summary>
    /// <param name="key">The cache key.</param>
    /// <param name="value">The value to store.</param>
    /// <param name="ttl">Override TTL. Uses the cache's default TTL if null.</param>
    public void Set(string key, TValue value, TimeSpan? ttl = null)
    {
        lock (_lock)
        {
            // If key already exists, remove it first to refresh insertion order.
            _store.Remove(key);

            // Evict oldest entry if at capacity.
            if (_store.Count >= _maxSize)
            {
                // Dictionary<K,V> enumerates in insertion order — first key is oldest.
                string? oldest = null;
                foreach (var k in _store.Keys)
                {
                    oldest = k;
                    break;
                }
                if (oldest != null)
                    _store.Remove(oldest);
            }

            _store[key] = new CacheEntry
            {
                Value = value,
                ExpiresAt = DateTime.UtcNow + (ttl ?? _defaultTtl)
            };
        }
    }

    /// <summary>Removes a specific key from the cache.</summary>
    public void Delete(string key)
    {
        lock (_lock)
        {
            _store.Remove(key);
        }
    }

    /// <summary>Removes all entries from the cache.</summary>
    public void Clear()
    {
        lock (_lock)
        {
            _store.Clear();
        }
    }

    /// <summary>Returns the current number of entries in the cache (including expired ones not yet purged).</summary>
    public int Count
    {
        get
        {
            lock (_lock)
            {
                return _store.Count;
            }
        }
    }

    /// <summary>
    /// Returns the number of non-expired entries in the cache.
    /// Note: This iterates through all entries and is O(n).
    /// </summary>
    public int ActiveCount
    {
        get
        {
            lock (_lock)
            {
                var now = DateTime.UtcNow;
                int count = 0;
                foreach (var entry in _store.Values)
                {
                    if (now < entry.ExpiresAt)
                        count++;
                }
                return count;
            }
        }
    }
}

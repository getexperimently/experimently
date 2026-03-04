import Foundation

// MARK: - CacheBox

/// A reference-type wrapper that stores a value alongside its expiry date.
/// Required because NSCache only accepts AnyObject as its value type.
private final class CacheBox<T> {
    let value: T
    let expiresAt: Date

    init(_ value: T, expiresAt: Date) {
        self.value = value
        self.expiresAt = expiresAt
    }

    var isExpired: Bool { Date() > expiresAt }
}

// MARK: - Cache

/// A thread-safe, size-bounded, TTL-aware cache backed by NSCache.
///
/// Key must be an `AnyObject` subclass (e.g., `NSString`).
/// Value can be any Swift type; it is wrapped internally in a `CacheBox`.
public final class Cache<Key: AnyObject, Value: AnyObject> {
    private let nsCache: NSCache<Key, CacheBox<Value>>
    private let ttl: TimeInterval
    private let lock = NSLock()

    /// - Parameters:
    ///   - maxSize: Maximum number of entries. NSCache may evict earlier under memory pressure.
    ///   - ttl: Time-to-live for each entry in seconds.
    public init(maxSize: Int, ttl: TimeInterval) {
        self.ttl = ttl
        self.nsCache = NSCache<Key, CacheBox<Value>>()
        self.nsCache.countLimit = maxSize
    }

    /// Returns the cached value for `key`, or `nil` if it is absent or expired.
    public func get(_ key: Key) -> Value? {
        lock.lock()
        defer { lock.unlock() }
        guard let box = nsCache.object(forKey: key) else { return nil }
        if box.isExpired {
            nsCache.removeObject(forKey: key)
            return nil
        }
        return box.value
    }

    /// Stores `value` under `key` with a TTL expiry.
    public func set(_ key: Key, value: Value) {
        lock.lock()
        defer { lock.unlock() }
        let box = CacheBox(value, expiresAt: Date().addingTimeInterval(ttl))
        nsCache.setObject(box, forKey: key)
    }

    /// Removes the entry for `key`.
    public func remove(_ key: Key) {
        lock.lock()
        defer { lock.unlock() }
        nsCache.removeObject(forKey: key)
    }

    /// Removes all cached entries.
    public func removeAll() {
        lock.lock()
        defer { lock.unlock() }
        nsCache.removeAllObjects()
    }
}

// MARK: - FlagCache

/// A thread-safe, string-keyed cache specifically for `FeatureFlag` objects with TTL support.
///
/// This is a simpler alternative to `Cache<NSString, AnyObject>` for the common case of
/// caching feature flags by their string keys.
public final class FlagCache {
    private var store: [String: (flag: FeatureFlag, expiresAt: Date)] = [:]
    private let lock = NSLock()
    private let ttl: TimeInterval

    /// - Parameter ttl: Time-to-live for each cached flag, in seconds. Default is 5 minutes.
    public init(ttl: TimeInterval = 300) {
        self.ttl = ttl
    }

    /// Returns the cached `FeatureFlag` for `key`, or `nil` if absent or expired.
    public func get(_ key: String) -> FeatureFlag? {
        lock.lock()
        defer { lock.unlock() }
        guard let entry = store[key] else { return nil }
        if Date() > entry.expiresAt {
            store.removeValue(forKey: key)
            return nil
        }
        return entry.flag
    }

    /// Stores a `FeatureFlag` under its `.key`, with a TTL expiry.
    public func set(_ key: String, flag: FeatureFlag) {
        lock.lock()
        defer { lock.unlock() }
        store[key] = (flag: flag, expiresAt: Date().addingTimeInterval(ttl))
    }

    /// Removes all cached flags.
    public func removeAll() {
        lock.lock()
        defer { lock.unlock() }
        store.removeAll()
    }

    /// The number of flags currently in the cache (including potentially expired ones
    /// not yet evicted by a get call).
    public var count: Int {
        lock.lock()
        defer { lock.unlock() }
        return store.count
    }
}

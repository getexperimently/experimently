import Foundation

/// UserDefaults-based persistent storage for offline fallback.
///
/// When the network is unavailable, the SDK can serve the last known flag values
/// that were persisted by this store during a previous successful fetch.
///
/// Keys are stored with a configurable prefix to avoid collisions with other
/// application data.
public final class OfflineStore {
    private let defaults: UserDefaults
    private let keyPrefix: String
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    /// Key used to store the full list of flag keys for bulk load.
    private var allFlagsIndexKey: String { keyPrefix + "_index" }

    /// - Parameters:
    ///   - suiteName: An App Group suite name for sharing data between app and extensions.
    ///                Pass `nil` to use `UserDefaults.standard`.
    ///   - keyPrefix: Prefix prepended to all stored keys. Default is `"ep_sdk_"`.
    public init(suiteName: String? = nil, keyPrefix: String = "ep_sdk_") {
        self.defaults = suiteName.flatMap { UserDefaults(suiteName: $0) } ?? .standard
        self.keyPrefix = keyPrefix
    }

    // MARK: - Single Flag Operations

    /// Persists a single feature flag to UserDefaults.
    ///
    /// - Parameter flag: The feature flag to save. Uses `flag.key` as the storage key.
    public func saveFlag(_ flag: FeatureFlag) {
        guard let data = try? encoder.encode(flag) else { return }
        defaults.set(data, forKey: storageKey(flag.key))
        addToIndex(flag.key)
    }

    /// Loads a single feature flag from UserDefaults by its key.
    ///
    /// - Parameter key: The feature flag key to retrieve.
    /// - Returns: The stored `FeatureFlag`, or `nil` if not found or corrupted.
    public func loadFlag(_ key: String) -> FeatureFlag? {
        guard let data = defaults.data(forKey: storageKey(key)) else { return nil }
        return try? decoder.decode(FeatureFlag.self, from: data)
    }

    // MARK: - Bulk Operations

    /// Saves all provided flags and updates the index.
    ///
    /// - Parameter flags: An array of feature flags to persist.
    public func saveAllFlags(_ flags: [FeatureFlag]) {
        var keys: [String] = []
        for flag in flags {
            if let data = try? encoder.encode(flag) {
                defaults.set(data, forKey: storageKey(flag.key))
                keys.append(flag.key)
            }
        }
        defaults.set(keys, forKey: allFlagsIndexKey)
    }

    /// Loads all previously saved flags.
    ///
    /// - Returns: An array of all `FeatureFlag` objects that were persisted. Returns
    ///   an empty array if nothing was saved or the data is corrupted.
    public func loadAllFlags() -> [FeatureFlag] {
        guard let keys = defaults.array(forKey: allFlagsIndexKey) as? [String] else {
            return []
        }
        return keys.compactMap { loadFlag($0) }
    }

    /// Removes all SDK-related data from UserDefaults, including the index.
    public func clearAll() {
        // Remove individual flag entries using the index.
        if let keys = defaults.array(forKey: allFlagsIndexKey) as? [String] {
            for key in keys {
                defaults.removeObject(forKey: storageKey(key))
            }
        }
        defaults.removeObject(forKey: allFlagsIndexKey)
    }

    // MARK: - Private Helpers

    private func storageKey(_ key: String) -> String {
        keyPrefix + key
    }

    private func addToIndex(_ key: String) {
        var keys = (defaults.array(forKey: allFlagsIndexKey) as? [String]) ?? []
        if !keys.contains(key) {
            keys.append(key)
            defaults.set(keys, forKey: allFlagsIndexKey)
        }
    }
}

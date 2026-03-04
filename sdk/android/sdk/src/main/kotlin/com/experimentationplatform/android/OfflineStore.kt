package com.experimentationplatform.android

import org.json.JSONArray
import org.json.JSONObject

/**
 * Offline fallback storage for feature flags.
 *
 * In production, backed by Android SharedPreferences.
 * In test environments (no Android context), falls back to an in-memory map.
 * Uses a SharedPreferences interface abstraction so both paths share the same logic.
 */
class OfflineStore(
    private val prefs: PrefsAdapter? = null  // null = use in-memory for tests
) {
    /**
     * Minimal SharedPreferences-like abstraction allowing test-time substitution.
     */
    interface PrefsAdapter {
        fun getString(key: String): String?
        fun putString(key: String, value: String)
        fun remove(key: String)
        fun allKeys(): Set<String>
        fun clear()
    }

    private val inMemory = mutableMapOf<String, String>()

    private fun rawGet(key: String): String? =
        prefs?.getString(key) ?: inMemory[key]

    private fun rawPut(key: String, value: String) {
        prefs?.putString(key, value) ?: run { inMemory[key] = value }
    }

    private fun rawRemove(key: String) {
        prefs?.remove(key) ?: inMemory.remove(key)
    }

    private fun rawAllKeys(): Set<String> =
        prefs?.allKeys() ?: inMemory.keys.toSet()

    private fun rawClear() {
        prefs?.clear() ?: inMemory.clear()
    }

    /**
     * Persists a single feature flag.
     */
    fun saveFlag(flag: FeatureFlag) {
        rawPut(flagKey(flag.key), flagToJson(flag).toString())
    }

    /**
     * Retrieves a feature flag by its key. Returns null if not found or corrupt.
     */
    fun loadFlag(key: String): FeatureFlag? {
        val raw = rawGet(flagKey(key)) ?: return null
        return try {
            FeatureFlag.fromJson(JSONObject(raw))
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Persists multiple flags at once.
     */
    fun saveAllFlags(flags: List<FeatureFlag>) {
        flags.forEach { saveFlag(it) }
    }

    /**
     * Loads all stored flags.
     */
    fun loadAllFlags(): List<FeatureFlag> {
        val prefix = "ep_flag_"
        return rawAllKeys()
            .filter { it.startsWith(prefix) }
            .mapNotNull { loadFlag(it.removePrefix(prefix)) }
    }

    /**
     * Removes a flag from storage.
     */
    fun removeFlag(key: String) {
        rawRemove(flagKey(key))
    }

    /**
     * Clears all stored flags.
     */
    fun clearAll() {
        rawClear()
    }

    private fun flagKey(key: String) = "ep_flag_$key"

    private fun flagToJson(flag: FeatureFlag): JSONObject {
        val variantsArray = JSONArray()
        flag.variants.forEach { variant ->
            variantsArray.put(JSONObject().apply {
                put("key", variant.key)
                put("weight", variant.weight)
                variant.value?.let { put("value", it) }
            })
        }
        return JSONObject().apply {
            put("key", flag.key)
            put("enabled", flag.enabled)
            put("rollout_percentage", flag.rolloutPercentage)
            put("variants", variantsArray)
        }
    }
}

package com.experimentationplatform.android

import org.json.JSONArray
import org.json.JSONObject

/**
 * SDK Configuration
 */
data class SdkConfig(
    val baseUrl: String = "http://localhost:8000",
    val apiKey: String,
    val timeoutMs: Long = 10_000L,
    val cacheSize: Int = 1000,
    val cacheTtlMs: Long = 300_000L, // 5 minutes
    val enableLocalEval: Boolean = true
)

/**
 * Platform user for flag evaluation
 */
data class User(
    val id: String,
    val attributes: Map<String, Any?> = emptyMap()
)

/**
 * Feature flag definition
 */
data class FeatureFlag(
    val key: String,
    val enabled: Boolean,
    val rolloutPercentage: Double,
    val variants: List<Variant> = emptyList()
) {
    companion object {
        fun fromJson(json: JSONObject): FeatureFlag {
            val variantsArray = json.optJSONArray("variants") ?: JSONArray()
            val variants = mutableListOf<Variant>()
            for (i in 0 until variantsArray.length()) {
                variants.add(Variant.fromJson(variantsArray.getJSONObject(i)))
            }
            return FeatureFlag(
                key = json.getString("key"),
                enabled = json.getBoolean("enabled"),
                rolloutPercentage = json.getDouble("rollout_percentage"),
                variants = variants
            )
        }
    }
}

/**
 * Variant within a feature flag
 */
data class Variant(
    val key: String,
    val weight: Double,
    val value: Any? = null
) {
    companion object {
        fun fromJson(json: JSONObject): Variant {
            return Variant(
                key = json.optString("key", json.optString("name", "")),
                weight = json.getDouble("weight"),
                value = if (json.has("value")) json.opt("value") else null
            )
        }
    }
}

/**
 * Experiment assignment result
 */
data class Assignment(
    val experimentKey: String,
    val variantKey: String,
    val userId: String
) {
    companion object {
        fun fromJson(json: JSONObject): Assignment {
            return Assignment(
                experimentKey = json.optString("experiment_key", ""),
                variantKey = json.optString("variant_key", ""),
                userId = json.optString("user_id", "")
            )
        }
    }
}

/**
 * Flag evaluation result
 */
data class EvalResult(
    val enabled: Boolean,
    val variantKey: String? = null,
    val value: Any? = null,
    val reason: String
)

/**
 * Tracking event
 */
data class TrackEvent(
    val userId: String,
    val eventName: String,
    val properties: Map<String, Any?> = emptyMap()
) {
    fun toJson(): JSONObject {
        val propertiesJson = JSONObject()
        properties.forEach { (k, v) ->
            when (v) {
                null -> propertiesJson.put(k, JSONObject.NULL)
                is Boolean -> propertiesJson.put(k, v)
                is Int -> propertiesJson.put(k, v)
                is Long -> propertiesJson.put(k, v)
                is Double -> propertiesJson.put(k, v)
                is Float -> propertiesJson.put(k, v.toDouble())
                else -> propertiesJson.put(k, v.toString())
            }
        }
        return JSONObject().apply {
            put("user_id", userId)
            put("event_name", eventName)
            put("properties", propertiesJson)
        }
    }
}

/**
 * SDK exceptions
 */
sealed class ExperimentationException(message: String, cause: Throwable? = null) :
    Exception(message, cause) {

    class NetworkException(message: String, cause: Throwable? = null) :
        ExperimentationException(message, cause)

    class FlagNotFoundException(flagKey: String) :
        ExperimentationException("Flag not found: $flagKey")

    class ServerException(val statusCode: Int, message: String) :
        ExperimentationException("Server error $statusCode: $message")

    class InvalidConfigException(message: String) :
        ExperimentationException(message)
}

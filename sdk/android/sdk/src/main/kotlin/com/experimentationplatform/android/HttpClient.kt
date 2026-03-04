package com.experimentationplatform.android

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * OkHttp-based HTTP client with Kotlin Coroutine support.
 *
 * Handles authentication via API key header, JSON serialization,
 * and proper error mapping to SDK exception types.
 */
class HttpClient(
    private val baseUrl: String,
    private val apiKey: String,
    timeoutMs: Long = 10_000L,
    private val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .writeTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .build()
) {
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    /**
     * Performs an authenticated GET request and returns the parsed JSON body.
     *
     * @param path API path relative to baseUrl (e.g. "/api/v1/feature-flags/my-flag")
     * @throws ExperimentationException.ServerException on non-2xx HTTP status
     * @throws ExperimentationException.NetworkException on IO errors
     */
    suspend fun get(path: String): JSONObject = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(normalizeUrl(path))
            .header("Authorization", "ApiKey $apiKey")
            .header("Accept", "application/json")
            .get()
            .build()

        executeRequest(request)
    }

    /**
     * Performs an authenticated POST request with a JSON body.
     *
     * @param path API path relative to baseUrl
     * @param body JSON body to send
     * @return parsed JSON response body
     * @throws ExperimentationException.ServerException on non-2xx HTTP status
     * @throws ExperimentationException.NetworkException on IO errors
     */
    suspend fun post(path: String, body: JSONObject): JSONObject = withContext(Dispatchers.IO) {
        val requestBody = body.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(normalizeUrl(path))
            .header("Authorization", "ApiKey $apiKey")
            .header("Accept", "application/json")
            .post(requestBody)
            .build()

        executeRequest(request)
    }

    /**
     * Fire-and-forget POST — enqueues asynchronously without suspending.
     * Errors are silently swallowed (suitable for analytics/tracking).
     *
     * @param path API path relative to baseUrl
     * @param body JSON body to send
     */
    fun postAsync(path: String, body: JSONObject) {
        val requestBody = body.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(normalizeUrl(path))
            .header("Authorization", "ApiKey $apiKey")
            .post(requestBody)
            .build()

        okHttpClient.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { /* intentionally ignored */ }
            override fun onResponse(call: Call, response: Response) { response.close() }
        })
    }

    private fun executeRequest(request: Request): JSONObject {
        return try {
            okHttpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    throw ExperimentationException.ServerException(
                        response.code,
                        response.message
                    )
                }
                val bodyString = response.body?.string() ?: "{}"
                JSONObject(bodyString)
            }
        } catch (e: ExperimentationException) {
            throw e
        } catch (e: IOException) {
            throw ExperimentationException.NetworkException(
                "Network error: ${e.message}",
                e
            )
        }
    }

    private fun normalizeUrl(path: String): String {
        val base = baseUrl.trimEnd('/')
        val p = if (path.startsWith("/")) path else "/$path"
        return "$base$p"
    }
}

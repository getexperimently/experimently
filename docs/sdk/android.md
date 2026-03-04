# Android Kotlin SDK

The Android SDK provides feature flag evaluation, experiment variant assignment, and event tracking for Android applications. It is built on Kotlin Coroutines and OkHttp, supports offline fallback via `SharedPreferences`, and requires no Android runtime for unit testing.

---

## Requirements

- Android minSdk 21 (Android 5.0 Lollipop)
- Kotlin 1.7+
- Coroutines 1.6+
- Gradle 7.0+

---

## Installation

### Gradle (Kotlin DSL)

```kotlin
// build.gradle.kts (app module)
dependencies {
    implementation("com.experimentationplatform:android-sdk:1.0.0")
}
```

### Gradle (Groovy DSL)

```groovy
// build.gradle (app module)
dependencies {
    implementation 'com.experimentationplatform:android-sdk:1.0.0'
}
```

### Local Module (from source)

```kotlin
// settings.gradle.kts
include(":sdk")
project(":sdk").projectDir = file("../sdk/android")

// build.gradle.kts (app module)
dependencies {
    implementation(project(":sdk"))
}
```

---

## Quick Start

```kotlin
import com.experimentationplatform.sdk.ExperimentationClient
import com.experimentationplatform.sdk.SdkConfig
import com.experimentationplatform.sdk.User

val client = ExperimentationClient(SdkConfig(
    baseUrl = "https://api.example.com",
    apiKey = "your-api-key"
))

lifecycleScope.launch {
    val result = client.evaluateFlag("new-feature", User(id = "user-123"))
    if (result.enabled) {
        showNewFeature()
    }
}
```

---

## Configuration

Construct `SdkConfig` with all desired settings and pass it to `ExperimentationClient`.

```kotlin
import com.experimentationplatform.sdk.SdkConfig

val config = SdkConfig(
    baseUrl = "https://api.example.com",     // Required
    apiKey = "your-api-key",                  // Required
    timeoutMs = 2_000L,                       // HTTP timeout in ms (default: 5000)
    cacheSize = 500,                          // LRU cache capacity (default: 1000)
    cacheTtlMs = 30_000L,                     // Cache TTL in ms (default: 60000)
    enableLocalEval = true,                   // Evaluate locally (default: false)
    enableOfflineFallback = true,             // SharedPreferences fallback (default: true)
    defaultVariant = "control"                // Fallback variant on error (default: "control")
)

val client = ExperimentationClient(config)
```

### `SdkConfig` Reference

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `baseUrl` | `String` | *(required)* | Base URL of the platform API |
| `apiKey` | `String` | *(required)* | API key for SDK authentication |
| `timeoutMs` | `Long` | `5000` | OkHttp call timeout in milliseconds |
| `cacheSize` | `Int` | `1000` | Maximum LRU cache entries |
| `cacheTtlMs` | `Long` | `60000` | Milliseconds before a cached entry expires |
| `enableLocalEval` | `Boolean` | `false` | Download rules and evaluate locally |
| `enableOfflineFallback` | `Boolean` | `true` | Persist last-known values to `SharedPreferences` |
| `defaultVariant` | `String` | `"control"` | Variant returned when assignment fails |

---

## Lifecycle Management

The client manages an internal OkHttp connection pool and an event-flush coroutine. Call `close()` when the client is no longer needed — typically in `onDestroy` or in a `ViewModel.onCleared`.

```kotlin
// In a ViewModel (recommended)
class CheckoutViewModel : ViewModel() {
    val expClient = ExperimentationClient(SdkConfig(
        baseUrl = BuildConfig.EXP_BASE_URL,
        apiKey = BuildConfig.EXP_API_KEY
    ))

    override fun onCleared() {
        expClient.close()
        super.onCleared()
    }
}
```

For application-scoped clients (singleton), close is optional since the process will terminate, but calling it ensures the event buffer is flushed.

---

## User Model

```kotlin
import com.experimentationplatform.sdk.User

// Minimal user
val user = User(id = "user-123")

// User with targeting attributes
val user = User(
    id = "user-123",
    attributes = mapOf(
        "plan"    to "pro",
        "country" to "US",
        "age"     to 28,
        "beta"    to true
    )
)
```

Attribute values may be `String`, `Int`, `Long`, `Double`, or `Boolean`.

---

## Feature Flag Evaluation

### `evaluateFlag`

This is a `suspend` function; call it from a coroutine scope.

```kotlin
lifecycleScope.launch {
    val result = client.evaluateFlag(
        flagKey = "new-feature",
        user = User(id = "user-123")
    )
    if (result.enabled) {
        showNewFeature()
    }
}
```

With user attributes for targeting:

```kotlin
lifecycleScope.launch {
    val user = User(
        id = currentUser.id,
        attributes = mapOf(
            "plan"    to currentUser.plan,
            "country" to currentUser.country
        )
    )
    val result = client.evaluateFlag("premium-dashboard", user)
    binding.dashboardContainer.isVisible = result.enabled
}
```

### `FlagResult` Properties

| Property | Type | Description |
|----------|------|-------------|
| `enabled` | `Boolean` | Whether the flag is on for this user |
| `flagKey` | `String` | The evaluated flag key |
| `userId` | `String` | The user ID used for evaluation |
| `evaluatedAt` | `Instant` | Timestamp of the evaluation |

---

## Experiment Assignment

### `getAssignment`

```kotlin
lifecycleScope.launch {
    val assignment = client.getAssignment(
        experimentKey = "checkout-experiment",
        user = User(id = "user-123")
    )

    when (assignment.variantKey) {
        "express-checkout" -> showExpressCheckout()
        "standard-checkout" -> showStandardCheckout()
        else -> showStandardCheckout()
    }
}
```

### `Assignment` Properties

| Property | Type | Description |
|----------|------|-------------|
| `variantKey` | `String` | Assigned variant key |
| `experimentKey` | `String` | The experiment key |
| `experimentId` | `String` | UUID of the experiment |
| `isControl` | `Boolean` | `true` if this is the control variant |
| `assignedAt` | `Instant` | Assignment timestamp |

---

## Event Tracking

### `track` (suspend)

```kotlin
lifecycleScope.launch {
    client.track(
        userID = "user-123",
        eventName = "purchase_completed",
        value = 49.99,
        properties = mapOf("currency" to "USD", "sku" to "pro-annual")
    )
}
```

### Fire-and-Forget with `trackAsync`

Use `trackAsync` in UI event handlers where you do not want to block or propagate errors to the caller.

```kotlin
binding.buyButton.setOnClickListener {
    // Does not suspend; enqueues the event internally
    client.trackAsync(
        userID = currentUser.id,
        eventName = "buy_button_tapped"
    )
}
```

`trackAsync` enqueues events in an internal `Channel` and flushes them to the platform in batches. Calling `client.close()` drains the buffer before shutdown.

---

## Offline Fallback

When `enableOfflineFallback = true`, every successful evaluation result is written to `SharedPreferences`. If a subsequent call fails due to no connectivity, the SDK returns the last-known value.

```kotlin
// Requires the application Context to access SharedPreferences
val client = ExperimentationClient(
    config = SdkConfig(
        baseUrl = "https://api.example.com",
        apiKey = "your-api-key",
        enableOfflineFallback = true
    ),
    context = applicationContext // Pass Context for SharedPreferences access
)
```

To clear the offline cache:

```kotlin
client.clearOfflineCache()
```

---

## Jetpack Compose Integration

### Feature Flag in a Composable

```kotlin
import androidx.compose.runtime.*
import com.experimentationplatform.sdk.ExperimentationClient
import com.experimentationplatform.sdk.User

@Composable
fun DashboardScreen(client: ExperimentationClient, user: User) {
    var showNewDashboard by remember { mutableStateOf(false) }

    LaunchedEffect(user.id) {
        val result = client.evaluateFlag("new-dashboard", user)
        showNewDashboard = result.enabled
    }

    if (showNewDashboard) {
        NewDashboard()
    } else {
        LegacyDashboard()
    }
}
```

### ViewModel Integration (recommended for production)

```kotlin
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

data class CheckoutUiState(
    val checkoutVariant: String = "control",
    val showNewUI: Boolean = false,
    val isLoading: Boolean = true
)

class CheckoutViewModel(
    private val client: ExperimentationClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(CheckoutUiState())
    val uiState: StateFlow<CheckoutUiState> = _uiState

    fun loadForUser(user: User) {
        viewModelScope.launch {
            val assignment = client.getAssignment("checkout-flow", user)
            val flag = client.evaluateFlag("new-ui", user)

            _uiState.value = CheckoutUiState(
                checkoutVariant = assignment.variantKey,
                showNewUI = flag.enabled,
                isLoading = false
            )
        }
    }
}

@Composable
fun CheckoutScreen(viewModel: CheckoutViewModel = viewModel()) {
    val uiState by viewModel.uiState.collectAsState()

    if (uiState.isLoading) {
        CircularProgressIndicator()
    } else {
        Column {
            Text("Variant: ${uiState.checkoutVariant}")
            if (uiState.showNewUI) NewCheckoutUI() else LegacyCheckoutUI()
        }
    }
}
```

---

## Error Handling

SDK methods throw `ExperimentationException` subclasses on unrecoverable failures.

```kotlin
try {
    val result = client.evaluateFlag("my-flag", user)
} catch (e: ExperimentationException.NetworkException) {
    // OkHttp IO or timeout error
    Timber.e(e, "Network error evaluating flag")
    // Offline fallback was already attempted; serve the default
} catch (e: ExperimentationException.ApiException) {
    // Non-2xx HTTP response
    Timber.e("API error ${e.statusCode}: ${e.message}")
} catch (e: ExperimentationException.ConfigurationException) {
    // Invalid SdkConfig (empty apiKey, malformed URL)
    Timber.e("SDK misconfigured: ${e.message}")
}
```

### `ExperimentationException` Hierarchy

| Class | Description |
|-------|-------------|
| `NetworkException(cause: Throwable)` | IO failure or timeout from OkHttp |
| `ApiException(statusCode: Int, message: String)` | Non-2xx HTTP response |
| `DecodingException(cause: Throwable)` | Response body could not be parsed |
| `ConfigurationException(message: String)` | Invalid SDK configuration |
| `OfflineFallbackUnavailableException` | Offline and no cached value exists |

---

## ProGuard / R8 Rules

If you have minification enabled, add the following to your `proguard-rules.pro`:

```proguard
# Experimentation Platform Android SDK
-keep class com.experimentationplatform.sdk.** { *; }
-keepnames class com.experimentationplatform.sdk.** { *; }

# OkHttp (included transitively)
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }
```

If you use R8 full mode (`android.enableR8.fullMode=true`), also add:

```proguard
-if class com.experimentationplatform.sdk.**
-keep class com.experimentationplatform.sdk.**$** { *; }
```

---

## Testing

### MockWebServer (unit + integration)

The SDK is designed to work with `MockWebServer` from OkHttp for hermetic tests. No Android instrumentation is required for unit tests.

```kotlin
import com.squareup.okhttp3.mockwebserver.MockResponse
import com.squareup.okhttp3.mockwebserver.MockWebServer
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class FeatureFlagTest {
    private lateinit var server: MockWebServer
    private lateinit var client: ExperimentationClient

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()

        client = ExperimentationClient(SdkConfig(
            baseUrl = server.url("/").toString(),
            apiKey = "test-key",
            enableOfflineFallback = false
        ))
    }

    @After
    fun tearDown() {
        server.shutdown()
        client.close()
    }

    @Test
    fun `evaluateFlag returns enabled when API responds with enabled true`() = runTest {
        server.enqueue(MockResponse()
            .setResponseCode(200)
            .setBody("""{"enabled": true, "flag_key": "new-feature", "user_id": "u1"}""")
            .addHeader("Content-Type", "application/json")
        )

        val result = client.evaluateFlag("new-feature", User(id = "u1"))

        assertTrue(result.enabled)
    }

    @Test
    fun `evaluateFlag returns disabled on 500 error`() = runTest {
        server.enqueue(MockResponse().setResponseCode(500))

        val result = client.evaluateFlag("new-feature", User(id = "u1"))

        assertTrue(!result.enabled)
    }
}
```

### Testing with Fakes

For unit tests of ViewModels or business logic, use the `FakeExperimentationClient` included in the SDK test artifact:

```kotlin
// build.gradle.kts (test dependencies)
testImplementation("com.experimentationplatform:android-sdk-testing:1.0.0")
```

```kotlin
import com.experimentationplatform.sdk.testing.FakeExperimentationClient

class CheckoutViewModelTest {
    @Test
    fun `loads treatment variant for experiment`() = runTest {
        val fakeClient = FakeExperimentationClient()
        fakeClient.setVariant("checkout-flow", "express-checkout")

        val viewModel = CheckoutViewModel(fakeClient)
        viewModel.loadForUser(User(id = "u1"))

        assertEquals("express-checkout", viewModel.uiState.value.checkoutVariant)
    }
}
```

---

## Thread Safety

`ExperimentationClient` is safe for concurrent access from multiple coroutines. All internal state is protected by coroutine Mutex guards. You can share a single client instance across your entire application.

---

## Full Working Example

```kotlin
// Application.kt
class MyApplication : Application() {
    lateinit var expClient: ExperimentationClient

    override fun onCreate() {
        super.onCreate()
        expClient = ExperimentationClient(
            config = SdkConfig(
                baseUrl = BuildConfig.EXP_BASE_URL,
                apiKey = BuildConfig.EXP_API_KEY,
                timeoutMs = 2_000L,
                cacheSize = 2000,
                cacheTtlMs = 30_000L,
                enableOfflineFallback = true
            ),
            context = applicationContext
        )
    }

    override fun onTerminate() {
        expClient.close()
        super.onTerminate()
    }
}

// CheckoutActivity.kt
class CheckoutActivity : AppCompatActivity() {
    private val expClient get() = (application as MyApplication).expClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_checkout)

        val user = User(
            id = getCurrentUserId(),
            attributes = mapOf(
                "plan"    to getCurrentUserPlan(),
                "country" to Locale.getDefault().country
            )
        )

        lifecycleScope.launch {
            val flagResult = expClient.evaluateFlag("new-checkout-flow", user)
            val assignment = expClient.getAssignment("checkout-cta-copy", user)

            if (flagResult.enabled) showNewCheckoutFlow() else showLegacyCheckoutFlow()
            updateCtaCopy(assignment.variantKey)
        }

        binding.checkoutButton.setOnClickListener {
            expClient.trackAsync(
                userID = getCurrentUserId(),
                eventName = "checkout_button_tapped"
            )
            proceedToCheckout()
        }
    }
}
```

# Compose Example

This example demonstrates using the Experimently Android SDK with Jetpack Compose.

## Setup

Add the SDK dependency to your `build.gradle.kts`:

```kotlin
implementation(project(":sdk"))
```

Or, when published to Maven:

```kotlin
implementation("com.getexperimently:experimently-android:1.0.0")
```

## Usage

```kotlin
val client = ExperimentationClient(
    SdkConfig(baseUrl = "http://10.0.2.2:8000", apiKey = "your-api-key")   // sent as X-API-Key
)

// In a Composable:
var flagEnabled by remember { mutableStateOf(false) }
var variant by remember { mutableStateOf("") }

LaunchedEffect(Unit) {
    val user = User(id = "user-123")
    flagEnabled = client.evaluateFlag("new-feature", user).enabled        // server decides
    variant = client.getAssignment("checkout-flow", user).variantName     // sticky server-side
}
```

## Running the Example

1. Start the backend server from the repo root: `uvicorn backend.app.main:app --port 8000`
   and create an API key (for example with `python backend/scripts/seed_sdk_contract.py`).
2. Open the project in Android Studio and paste the key into `ExampleActivity.kt`.
3. Run on an emulator (use `http://10.0.2.2:8000` to reach localhost).
4. The app evaluates the `new-dashboard` flag and assigns `user-123` to `checkout-flow` on
   launch; the button tracks a `purchase_clicked` event attributed to that experiment.

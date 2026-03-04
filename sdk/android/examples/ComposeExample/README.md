# Compose Example

This example demonstrates using the Experimentation Platform Android SDK with Jetpack Compose.

## Setup

Add the SDK dependency to your `build.gradle.kts`:

```kotlin
implementation(project(":sdk"))
```

Or, when published to Maven:

```kotlin
implementation("com.experimentationplatform:android-sdk:1.0.0")
```

## Usage

```kotlin
val client = ExperimentationClient(
    SdkConfig(baseUrl = "http://10.0.2.2:8000", apiKey = "your-api-key")
)

// In a Composable:
var flagEnabled by remember { mutableStateOf(false) }

LaunchedEffect(Unit) {
    val result = client.evaluateFlag("new-feature", User(id = "user-123"))
    flagEnabled = result.enabled
}
```

## Running the Example

1. Start the backend server: `uvicorn app.main:app --reload`
2. Open the project in Android Studio.
3. Run on an emulator (use `http://10.0.2.2:8000` to reach localhost).
4. The app evaluates `new-dashboard` flag for `user-123` on launch.

# iOS Swift SDK

The iOS SDK provides feature flag evaluation, experiment variant assignment, and event tracking for Swift applications. It uses `async/await` for all network operations, requires zero external dependencies, and supports offline fallback via `UserDefaults`.

---

## Requirements

- iOS 14.0+ / macOS 11.0+
- Swift 5.5+
- Xcode 13+

---

## Installation

### Swift Package Manager

Add the package dependency in `Package.swift`:

```swift
// Package.swift
dependencies: [
    .package(
        url: "https://github.com/amarkanday/experimentation-platform",
        from: "1.0.0"
    )
],
targets: [
    .target(
        name: "MyApp",
        dependencies: [
            .product(name: "ExperimentationSDK", package: "experimentation-platform")
        ]
    )
]
```

Or from Xcode: **File → Add Package Dependencies** → enter the repository URL → select **Up to Next Major Version: 1.0.0**.

---

## Quick Start

```swift
import ExperimentationSDK

let client = ExperimentationClient(
    baseURL: "https://api.example.com",
    apiKey: "your-api-key"
)

let user = User(id: "user-123")
let result = try await client.evaluateFlag("new-dashboard", user: user)
if result.enabled {
    showNewDashboard()
}
```

---

## Configuration

Pass a `SdkConfig` instance to customise the client's behaviour.

```swift
import ExperimentationSDK

let config = SdkConfig(
    baseURL: "https://api.example.com",
    apiKey: "your-api-key",
    timeoutInterval: 2.0,        // Seconds (default: 5.0)
    cacheSize: 500,               // Maximum LRU entries (default: 1000)
    cacheTTL: 30.0,               // Seconds before a cache entry expires (default: 60.0)
    enableLocalEval: true,        // Evaluate flags locally (default: false)
    enableOfflineFallback: true,  // Cache to UserDefaults for offline use (default: true)
    defaultVariant: "control"     // Fallback variant on error (default: "control")
)

let client = ExperimentationClient(config: config)
```

### `SdkConfig` Reference

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `baseURL` | `String` | *(required)* | Base URL of the platform API |
| `apiKey` | `String` | *(required)* | API key for SDK authentication |
| `timeoutInterval` | `TimeInterval` | `5.0` | URLSession request timeout in seconds |
| `cacheSize` | `Int` | `1000` | Maximum number of cached evaluation results |
| `cacheTTL` | `TimeInterval` | `60.0` | Seconds before a cached entry is invalidated |
| `enableLocalEval` | `Bool` | `false` | Download rules and evaluate locally |
| `enableOfflineFallback` | `Bool` | `true` | Persist last-known values to `UserDefaults` |
| `defaultVariant` | `String` | `"control"` | Variant returned when assignment fails |

---

## User Model

```swift
import ExperimentationSDK

// Minimal user
let user = User(id: "user-123")

// User with targeting attributes
let user = User(
    id: "user-123",
    attributes: [
        "plan":    AnyCodable("pro"),
        "country": AnyCodable("US"),
        "age":     AnyCodable(28),
        "beta":    AnyCodable(true)
    ]
)
```

`AnyCodable` is a type-erased `Codable` wrapper included in the SDK. It accepts `String`, `Int`, `Double`, and `Bool` values.

---

## Feature Flag Evaluation

### `evaluateFlag(_:user:)`

```swift
do {
    let result = try await client.evaluateFlag("new-dashboard", user: user)
    if result.enabled {
        showNewDashboard()
    } else {
        showLegacyDashboard()
    }
} catch {
    // On error, result.enabled is false; the catch block is for strict error handling
    showLegacyDashboard()
}
```

### `FlagResult` Properties

| Property | Type | Description |
|----------|------|-------------|
| `enabled` | `Bool` | Whether the flag is on for this user |
| `flagKey` | `String` | The evaluated flag key |
| `userID` | `String` | The user ID used for evaluation |
| `evaluatedAt` | `Date` | Timestamp of the evaluation |

---

## Experiment Assignment

### `getAssignment(_:user:)`

```swift
do {
    let assignment = try await client.getAssignment("checkout-experiment", user: user)
    print(assignment.variantKey) // "control" or "treatment"

    switch assignment.variantKey {
    case "express-checkout":
        showExpressCheckout()
    case "standard-checkout":
        showStandardCheckout()
    default:
        showStandardCheckout()
    }
} catch {
    showStandardCheckout()
}
```

### `Assignment` Properties

| Property | Type | Description |
|----------|------|-------------|
| `variantKey` | `String` | Assigned variant key |
| `experimentKey` | `String` | The experiment key |
| `experimentID` | `String` | UUID of the experiment |
| `isControl` | `Bool` | `true` if this is the control variant |
| `assignedAt` | `Date` | Assignment timestamp |

---

## Event Tracking

### `track(_:)`

```swift
// Async (awaitable)
try await client.track(TrackEvent(
    userID: "user-123",
    eventName: "purchase",
    value: 49.99,
    properties: [
        "currency": AnyCodable("USD"),
        "sku":      AnyCodable("pro-annual")
    ]
))
```

### Fire-and-Forget

For UI events where you do not want to block the call site:

```swift
Task {
    try? await client.track(TrackEvent(
        userID: currentUser.id,
        eventName: "button_tapped",
        properties: ["button_id": AnyCodable("upgrade-cta")]
    ))
}
```

### `TrackEvent` Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `userID` | `String` | Yes | The user who performed the action |
| `eventName` | `String` | Yes | Event identifier |
| `value` | `Double?` | No | Numeric value (revenue, duration) |
| `properties` | `[String: AnyCodable]?` | No | Arbitrary metadata |
| `timestamp` | `Date` | No | Defaults to `Date()` |

---

## Offline Mode

When `enableOfflineFallback: true`, every successful evaluation result is persisted to `UserDefaults`. If a subsequent call fails due to no network connectivity, the SDK returns the last known value instead of an error.

```swift
// First call (online) — fetched from API and cached in UserDefaults
let result = try await client.evaluateFlag("new-feature", user: user)

// Later, device goes offline — returns cached value transparently
let result = try await client.evaluateFlag("new-feature", user: user)
// result.enabled == last known value
```

To clear the offline cache:

```swift
client.clearOfflineCache()
```

---

## SwiftUI Integration

### Feature Flag in a View

```swift
import SwiftUI
import ExperimentationSDK

struct DashboardView: View {
    @State private var showNewDashboard = false
    let client: ExperimentationClient
    let user: User

    var body: some View {
        Group {
            if showNewDashboard {
                NewDashboardView()
            } else {
                LegacyDashboardView()
            }
        }
        .task {
            let result = try? await client.evaluateFlag("new-dashboard", user: user)
            showNewDashboard = result?.enabled ?? false
        }
    }
}
```

### Observable Wrapper (iOS 17+)

```swift
import Observation
import ExperimentationSDK

@Observable
class ExperimentationState {
    var isDarkMode = false
    var checkoutVariant = "control"

    private let client: ExperimentationClient
    private let user: User

    init(client: ExperimentationClient, user: User) {
        self.client = client
        self.user = user
    }

    func load() async {
        async let flagResult = client.evaluateFlag("dark-mode", user: user)
        async let assignment = client.getAssignment("checkout-flow", user: user)

        isDarkMode = (try? await flagResult)?.enabled ?? false
        checkoutVariant = (try? await assignment)?.variantKey ?? "control"
    }
}
```

---

## Error Handling

All SDK methods throw `ExperimentationError` on failure.

```swift
do {
    let result = try await client.evaluateFlag("my-flag", user: user)
} catch ExperimentationError.networkFailure(let underlying) {
    // URLSession error; offline fallback was returned if enabled
    print("Network error: \(underlying.localizedDescription)")
} catch ExperimentationError.apiError(let statusCode, let message) {
    // Non-2xx HTTP response
    print("API \(statusCode): \(message)")
} catch ExperimentationError.invalidConfiguration(let reason) {
    // Misconfigured client (empty API key, invalid URL)
    print("Config error: \(reason)")
} catch {
    // Unexpected error
    print("Unknown error: \(error)")
}
```

### `ExperimentationError` Cases

| Case | Description |
|------|-------------|
| `.networkFailure(Error)` | Network connectivity issue or timeout |
| `.apiError(Int, String)` | Non-2xx HTTP response with status code and message |
| `.decodingError(Error)` | Response body could not be decoded |
| `.invalidConfiguration(String)` | Client was configured incorrectly |
| `.offlineFallbackUnavailable` | Offline and no cached value exists |

---

## Testing

### MockURLProtocol Pattern

Inject a mock `URLProtocol` to test code that calls the SDK without network access.

```swift
import XCTest
@testable import ExperimentationSDK

class MockURLProtocol: URLProtocol {
    static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = MockURLProtocol.requestHandler else {
            fatalError("No handler set")
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class FeatureFlagTests: XCTestCase {
    func testFlagEnabled() async throws {
        MockURLProtocol.requestHandler = { _ in
            let response = HTTPURLResponse(
                url: URL(string: "https://api.example.com")!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let data = """
            {"enabled": true, "flag_key": "new-checkout", "user_id": "user-123"}
            """.data(using: .utf8)!
            return (response, data)
        }

        let sessionConfig = URLSessionConfiguration.ephemeral
        sessionConfig.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: sessionConfig)

        let client = ExperimentationClient(
            baseURL: "https://api.example.com",
            apiKey: "test-key",
            urlSession: session
        )

        let user = User(id: "user-123")
        let result = try await client.evaluateFlag("new-checkout", user: user)
        XCTAssertTrue(result.enabled)
    }
}
```

---

## Thread Safety

`ExperimentationClient` is safe to use from multiple threads and Swift concurrency tasks. Internal state is protected by a serial actor; no external synchronization is required.

```swift
// All of these can run concurrently with no data races:
async let r1 = client.evaluateFlag("flag-a", user: user)
async let r2 = client.evaluateFlag("flag-b", user: user)
async let r3 = client.getAssignment("experiment-x", user: user)
let (flag1, flag2, assignment) = try await (r1, r2, r3)
```

---

## Full Working Example

```swift
import SwiftUI
import ExperimentationSDK

@main
struct ExampleApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

struct ContentView: View {
    private let client = ExperimentationClient(config: SdkConfig(
        baseURL: ProcessInfo.processInfo.environment["EXP_BASE_URL"] ?? "",
        apiKey:  ProcessInfo.processInfo.environment["EXP_API_KEY"] ?? "",
        enableOfflineFallback: true
    ))

    @State private var checkoutVariant = "control"
    @State private var showNewUI = false
    private let user = User(
        id: "user-456",
        attributes: ["plan": AnyCodable("pro"), "country": AnyCodable("US")]
    )

    var body: some View {
        VStack(spacing: 20) {
            Text("Checkout variant: \(checkoutVariant)")
            if showNewUI {
                Text("New UI is active")
                    .foregroundColor(.green)
            }
            Button("Complete Purchase") {
                Task {
                    try? await client.track(TrackEvent(
                        userID: user.id,
                        eventName: "purchase_completed",
                        value: 49.99
                    ))
                }
            }
        }
        .task {
            async let assignment = client.getAssignment("checkout-flow", user: user)
            async let flag = client.evaluateFlag("new-ui", user: user)

            checkoutVariant = (try? await assignment)?.variantKey ?? "control"
            showNewUI = (try? await flag)?.enabled ?? false
        }
    }
}
```

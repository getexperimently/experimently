# Java SDK

The Java SDK provides experiment variant assignment, feature flag evaluation, and event tracking for JVM applications. It includes an LRU cache with TTL support, consistent MD5-based hash bucketing, and a Spring Boot auto-configuration starter.

---

## Installation

### Maven (`pom.xml`)

```xml
<dependency>
    <groupId>com.experimently</groupId>
    <artifactId>experimently-sdk</artifactId>
    <version>1.0.0</version>
</dependency>
```

### Gradle (`build.gradle`)

```groovy
implementation 'com.experimently:experimently-sdk:1.0.0'
```

---

## Building the Client

```java
import com.experimently.sdk.ExperimentationClient;
import com.experimently.sdk.ExperimentationConfig;

ExperimentationClient client = ExperimentationClient.builder()
    .apiUrl("https://your-platform.example.com")
    .apiKey("your-api-key")
    .build();
```

### Configuration Options

```java
ExperimentationClient client = ExperimentationClient.builder()
    .apiUrl("https://your-platform.example.com")   // Required
    .apiKey("your-api-key")                         // Required
    .timeoutSeconds(2)                              // HTTP timeout (default: 5)
    .cacheTtlSeconds(60)                            // Cache TTL (default: 60)
    .cacheMaxSize(1000)                             // Max cache entries (default: 1000)
    .defaultVariant("control")                      // Fallback on error (default: "control")
    .build();
```

Close the client when your application shuts down to release the connection pool:

```java
client.close();
```

---

## Experiment Variant Assignment

### `getVariant(experimentKey, userId, attributes)`

Returns the variant key assigned to the user. Returns `defaultVariant` on error.

```java
import java.util.Map;

String variant = client.getVariant(
    "checkout-button-color",        // experimentKey
    "user-123",                     // userId
    Map.of("country", "US", "plan", "pro")  // targeting attributes
);

System.out.println(variant); // "control" or "treatment"

if ("treatment".equals(variant)) {
    showGreenButton();
} else {
    showBlueButton();
}
```

### Getting Full Assignment Metadata

```java
import com.experimently.sdk.Assignment;

Assignment assignment = client.getAssignment(
    "checkout-button-color",
    "user-123",
    Map.of("plan", "enterprise")
);

System.out.println(assignment.getVariantKey());    // "treatment"
System.out.println(assignment.getExperimentId());  // UUID string
System.out.println(assignment.isControl());        // false
System.out.println(assignment.getAssignedAt());    // ISO 8601 timestamp
```

---

## Feature Flag Evaluation

### `isFeatureEnabled(flagKey, userId, attributes)`

Returns `true` if the feature flag is enabled for the user, `false` otherwise (including on error).

```java
boolean enabled = client.isFeatureEnabled(
    "new-checkout-flow",    // flagKey
    "user-123",             // userId
    Map.of(
        "country", "US",
        "plan", "enterprise"
    )
);

if (enabled) {
    return handleNewCheckoutFlow(request);
} else {
    return handleCurrentCheckoutFlow(request);
}
```

---

## Event Tracking

### `trackEvent(userId, eventKey, value)`

Records a conversion or behavioral event. Pass `null` for `value` if no numeric value applies.

```java
// Simple event (no numeric value)
client.trackEvent("user-123", "page_view", null);

// Event with a numeric value
client.trackEvent("user-123", "purchase_completed", 149.00);

// Revenue tracking
client.trackEvent("user-123", "subscription_started", 29.99);
```

Tracking failures are logged internally but do not throw exceptions.

---

## LRU Cache with TTL

The SDK maintains an in-memory LRU cache for assignments and flag evaluations. The cache reduces network calls for high-traffic applications.

```java
ExperimentationClient client = ExperimentationClient.builder()
    .apiUrl("https://your-platform.example.com")
    .apiKey("your-api-key")
    .cacheTtlSeconds(60)    // Cache entries expire after 60 seconds
    .cacheMaxSize(1000)     // Maximum 1000 cached entries (LRU eviction when full)
    .build();
```

Default values:
- `cacheTtlSeconds`: 60 (1 minute)
- `cacheMaxSize`: 1000 entries

For applications with many unique users, increase `cacheMaxSize`. For faster propagation of flag changes, reduce `cacheTtlSeconds`.

---

## Consistent Hash Bucketing

The SDK uses **MD5-based consistent hashing** for deterministic variant assignment. The hash input is `"{experimentKey}:{userId}"`.

This guarantees:
- The same user always sees the same variant for a given experiment
- Assignment is stable across application restarts (within cache TTL)
- No sticky-session infrastructure is required
- Multiple SDK instances serving the same user return the same variant

---

## Thread Safety

The `ExperimentationClient` is thread-safe. A single client instance can be shared across all threads in a multi-threaded application without external synchronization.

```java
// Correct: share a single instance
@Bean
public ExperimentationClient experimentationClient() {
    return ExperimentationClient.builder()
        .apiUrl(apiUrl)
        .apiKey(apiKey)
        .build();
}

// Incorrect: do not create a new client per request
public String getVariantForRequest(HttpRequest request) {
    ExperimentationClient client = new ExperimentationClient(...); // wrong
    return client.getVariant(...);
}
```

---

## Spring Boot Auto-Configuration

Add the Spring Boot starter for zero-configuration integration:

### Maven

```xml
<dependency>
    <groupId>com.experimently</groupId>
    <artifactId>experimently-spring-boot-starter</artifactId>
    <version>1.0.0</version>
</dependency>
```

### Gradle

```groovy
implementation 'com.experimently:experimently-spring-boot-starter:1.0.0'
```

### Enable the Integration

Add `@EnableExperimentation` to your main application class:

```java
import com.experimently.spring.EnableExperimentation;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@EnableExperimentation
public class MyApplication {
    public static void main(String[] args) {
        SpringApplication.run(MyApplication.class, args);
    }
}
```

### Inject the Client

The `ExperimentationClient` bean is automatically configured and available for injection:

```java
import com.experimently.sdk.ExperimentationClient;
import org.springframework.stereotype.Service;

@Service
public class CheckoutService {

    private final ExperimentationClient experimentationClient;

    public CheckoutService(ExperimentationClient experimentationClient) {
        this.experimentationClient = experimentationClient;
    }

    public String resolveCheckoutVariant(String userId, String plan) {
        return experimentationClient.getVariant(
            "checkout-flow",
            userId,
            Map.of("plan", plan)
        );
    }
}
```

---

## Spring Boot Properties

Configure the SDK in `application.properties` or `application.yml`:

### `application.properties`

```properties
experimentation.api-url=https://your-platform.example.com
experimentation.api-key=${EXPERIMENTATION_API_KEY}
experimentation.cache-ttl-seconds=60
experimentation.cache-max-size=1000
experimentation.timeout-seconds=5
experimentation.default-variant=control
```

### `application.yml`

```yaml
experimentation:
  api-url: https://your-platform.example.com
  api-key: ${EXPERIMENTATION_API_KEY}
  cache-ttl-seconds: 60
  cache-max-size: 1000
  timeout-seconds: 5
  default-variant: control
```

### Properties Reference

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `experimentation.api-url` | `String` | *(required)* | Base URL of the platform API |
| `experimentation.api-key` | `String` | *(required)* | API key for SDK authentication |
| `experimentation.cache-ttl-seconds` | `int` | `60` | Seconds before a cached assignment expires |
| `experimentation.cache-max-size` | `int` | `1000` | Maximum cache entries (LRU eviction when full) |
| `experimentation.timeout-seconds` | `int` | `5` | HTTP request timeout in seconds |
| `experimentation.default-variant` | `String` | `"control"` | Variant returned when the API is unreachable |

---

## Error Handling and Fallback

The SDK handles errors gracefully without throwing exceptions from assignment and flag evaluation calls:

```java
// getVariant never throws — returns defaultVariant on any failure
String variant = client.getVariant("experiment-key", userId, Map.of());
// Returns "control" (defaultVariant) if API is unreachable or times out

// isFeatureEnabled never throws — returns false on any failure
boolean enabled = client.isFeatureEnabled("flag-key", userId, Map.of());
// Returns false if API is unreachable

// trackEvent logs failures but does not throw
client.trackEvent(userId, "purchase", 49.99);
```

To enable strict mode for tracking (throws on failure):

```java
client.trackEventStrict(userId, "purchase_completed", 49.99);
// Throws ExperimentationException if the event cannot be delivered
```

---

## Complete Usage Example

```java
import com.experimently.sdk.ExperimentationClient;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseBody;
import java.util.Map;

@Controller
public class CheckoutController {

    private final ExperimentationClient experimentationClient;

    public CheckoutController(ExperimentationClient experimentationClient) {
        this.experimentationClient = experimentationClient;
    }

    @PostMapping("/checkout")
    @ResponseBody
    public CheckoutResponse handleCheckout(@RequestBody CheckoutRequest request) {
        String userId = request.getUserId();
        String userPlan = request.getPlan();

        // Check feature flag
        boolean useNewCheckout = experimentationClient.isFeatureEnabled(
            "new-checkout-flow",
            userId,
            Map.of("plan", userPlan, "country", request.getCountry())
        );

        // Get experiment variant
        String ctaVariant = experimentationClient.getVariant(
            "checkout-cta-copy",
            userId,
            Map.of("plan", userPlan)
        );

        // Process checkout
        CheckoutResponse response = useNewCheckout
            ? processNewCheckout(request)
            : processLegacyCheckout(request);

        // Track the conversion
        experimentationClient.trackEvent(userId, "checkout_completed", request.getOrderValue());

        return response;
    }
}
```

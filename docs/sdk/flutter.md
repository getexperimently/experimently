# Flutter SDK

The Experimentation Platform Flutter SDK provides feature flag evaluation, A/B experiment assignment, and event tracking for Flutter applications. It works on iOS, Android, Web, macOS, Windows, and Linux.

## Features

- Local feature flag evaluation using consistent MD5 hashing (cross-SDK compatible)
- In-memory caching with configurable TTL
- SharedPreferences-backed offline fallback
- Fire-and-forget event tracking
- Null-safe Dart 2.17+ API

## Installation

Add the SDK to your `pubspec.yaml`:

```yaml
dependencies:
  flutter:
    sdk: flutter
  experimentation_sdk:
    git:
      url: https://github.com/experimentation-platform/sdk
      path: flutter
```

Or from pub.dev (once published):

```yaml
dependencies:
  experimentation_sdk: ^0.1.0
```

Then run:

```bash
flutter pub get
```

## Configuration

```dart
import 'package:experimentation_sdk/experimentation_sdk.dart';

final client = ExperimentationClient(
  config: SdkConfig(
    apiKey: 'your-api-key',
    baseUrl: 'https://api.getexperimently.com',
    cacheTtl: Duration(minutes: 5),      // default: 5 minutes
    timeout: Duration(seconds: 5),        // default: 5 seconds
    offlineFallback: true,                // default: true
  ),
);

// Always call init() before using the client.
await client.init();
```

## Basic Usage

### Feature Flag Evaluation

```dart
final enabled = await client.evaluateFlag(
  'dark-mode',
  'user-123',
  attributes: {'plan': 'pro', 'country': 'US'},
);

if (enabled) {
  // Show dark mode UI
}
```

### Experiment Assignment

```dart
final variant = await client.getAssignment(
  'checkout-experiment',
  'user-123',
);

switch (variant) {
  case 'treatment':
    // Show new checkout flow
    break;
  case 'control':
  default:
    // Show original checkout flow
    break;
}
```

### Event Tracking

```dart
// Fire-and-forget — never throws, safe to call without await.
await client.track(
  'button_clicked',
  'user-123',
  properties: {
    'button_id': 'checkout_cta',
    'screen': 'cart',
  },
);
```

## Evaluation Order

When `evaluateFlag` or `getAssignment` is called, the client follows this
priority order:

1. **In-memory cache** — returns the cached result if not expired.
2. **API call** — fetches the flag from the platform, evaluates locally using
   the consistent hash, writes the result to the in-memory cache and (if
   `offlineFallback: true`) to SharedPreferences.
3. **SharedPreferences fallback** — when `offlineFallback: true` and the API
   is unreachable, returns the last-known persisted value.
4. **Safe default** — returns `false` / `null` if no value is available.

## Offline Support

The SDK automatically writes evaluated results to SharedPreferences when
`offlineFallback: true` (the default). On subsequent app launches or when the
network is unavailable, the last-known values are served from disk.

```dart
// Offline fallback is enabled by default.
// The first successful API evaluation is persisted automatically.
final config = SdkConfig(
  apiKey: 'your-api-key',
  baseUrl: 'https://api.getexperimently.com',
  offlineFallback: true, // default
);
```

To disable offline fallback:

```dart
final config = SdkConfig(
  apiKey: 'your-api-key',
  baseUrl: 'https://api.getexperimently.com',
  offlineFallback: false,
);
```

## Resource Management

Close the client when it is no longer needed (e.g. when the app is disposed):

```dart
@override
void dispose() {
  client.close();
  super.dispose();
}
```

## Flutter Widget Integration

```dart
class FeatureFlagWidget extends StatefulWidget {
  const FeatureFlagWidget({super.key});
  @override
  State<FeatureFlagWidget> createState() => _FeatureFlagWidgetState();
}

class _FeatureFlagWidgetState extends State<FeatureFlagWidget> {
  bool _enabled = false;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _evaluate();
  }

  Future<void> _evaluate() async {
    final enabled = await client.evaluateFlag('new-ui', 'user-123');
    if (mounted) setState(() { _enabled = enabled; _loading = false; });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const CircularProgressIndicator();
    return Text(_enabled ? 'New UI' : 'Old UI');
  }
}
```

## Hash Algorithm

All SDKs use an identical consistent hash to ensure the same user always gets
the same assignment, regardless of which SDK they use:

```
MD5("{userId}:{flagKey}") → first 4 bytes as little-endian uint32 → ÷ 2^32
```

The divisor is **2^32 = 4294967296**, not `MaxUInt32` (4294967295). This
matches the Java, Python, Go, iOS, Android, and React Native SDKs exactly.

```dart
import 'package:experimentation_sdk/experimentation_sdk.dart';

// Direct hash access (for testing/debugging):
final h = hashUser('user-123', 'my-flag');
// h ≈ 0.6927449859  (verified against all SDK implementations)
```

## Testing Guide

### Mocking the Client

Inject a mock `ApiHttpClient` in tests instead of making real network calls:

```dart
import 'package:mockito/annotations.dart';
import 'package:mockito/mockito.dart';
import 'package:experimentation_sdk/experimentation_sdk.dart';

@GenerateMocks([ApiHttpClient])
import 'my_test.mocks.dart';

void main() {
  test('evaluateFlag returns true when API returns enabled flag', () async {
    final mockHttp = MockApiHttpClient();
    when(mockHttp.get(any)).thenAnswer((_) async => {
      'id': 'f1', 'key': 'my-flag', 'name': 'My Flag',
      'enabled': true, 'rollout_percentage': 100.0, 'variants': [],
    });

    final client = ExperimentationClient(
      config: SdkConfig(apiKey: 'test', baseUrl: 'https://example.com', offlineFallback: false),
      httpClient: mockHttp,
    );
    await client.init();

    expect(await client.evaluateFlag('my-flag', 'user-1'), isTrue);
  });
}
```

Generate mocks:

```bash
dart run build_runner build
```

Run tests:

```bash
flutter test
```

## Troubleshooting

### `StateError: init() must be called before using the client`

You must call `await client.init()` before any other method. Do this in your
app's startup sequence, e.g. in `main()` before `runApp()`.

### SharedPreferences not persisting on Web

SharedPreferences uses `window.localStorage` on Flutter Web. Ensure the user
has not disabled local storage in their browser.

### Hash values don't match other SDKs

Verify you are using the `hashUser()` function from this SDK, not a custom
implementation. The divisor must be `4294967296.0` (2^32), not `4294967295`.

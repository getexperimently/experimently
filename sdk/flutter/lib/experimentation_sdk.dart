/// Flutter SDK for the Experimentation Platform.
///
/// Feature-flag evaluation and A/B experiment assignment are decided by the
/// server (`/api/v1/feature-flags/evaluate/{key}` and
/// `/api/v1/tracking/assign`); results are cached per user + key with a TTL
/// and, optionally, persisted to SharedPreferences for offline fallback.
/// Event tracking never throws.
///
/// ## Getting Started
/// ```dart
/// import 'package:experimentation_sdk/experimentation_sdk.dart';
///
/// final client = ExperimentationClient(
///   config: SdkConfig(apiKey: 'your-api-key', baseUrl: 'https://api.example.com'),
///   offlineStore: SharedPreferencesOfflineStore(),
/// );
/// await client.init();
///
/// final flag = await client.evaluateFlag('dark-mode', 'user-123');
/// final assignment = await client.getAssignment('checkout-exp', 'user-123');
/// await client.track('purchase', 'user-123', experimentKey: 'checkout-exp', value: 12.5);
/// await client.close();
/// ```
///
/// For plain Dart (no Flutter) import `experimentation_sdk_core.dart` instead.
library experimentation_sdk;

export 'experimentation_sdk_core.dart';
export 'src/shared_preferences_offline_store.dart';

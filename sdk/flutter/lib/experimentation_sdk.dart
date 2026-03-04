/// Flutter SDK for the Experimentation Platform.
///
/// Provides feature-flag evaluation, A/B experiment assignment, and event
/// tracking with local consistent hashing, in-memory caching, and offline
/// SharedPreferences fallback.
///
/// ## Getting Started
/// ```dart
/// import 'package:experimentation_sdk/experimentation_sdk.dart';
///
/// final client = ExperimentationClient(
///   config: SdkConfig(
///     apiKey: 'your-api-key',
///     baseUrl: 'https://api.example.com',
///   ),
/// );
/// await client.init();
///
/// final enabled = await client.evaluateFlag('dark-mode', 'user-123');
/// final variant = await client.getAssignment('checkout-exp', 'user-123');
/// await client.track('page_viewed', 'user-123', properties: {'page': '/home'});
/// await client.close();
/// ```
library experimentation_sdk;

export 'src/models.dart';
export 'src/evaluator.dart' show hashUser, FeatureFlagEvaluator;
export 'src/cache.dart';
export 'src/http_client.dart';
export 'src/offline_store.dart';
export 'src/client.dart';

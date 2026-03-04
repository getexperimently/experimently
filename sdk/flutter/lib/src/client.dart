/// Main ExperimentationClient for the Flutter SDK.
library experimentation_sdk_client;

import 'models.dart';
import 'evaluator.dart';
import 'cache.dart';
import 'http_client.dart';
import 'offline_store.dart';

/// Flutter/Dart client for the Experimentation Platform.
///
/// Provides feature-flag evaluation, experiment assignment, and event
/// tracking. Evaluations are cached in memory (with configurable TTL) and,
/// when [SdkConfig.offlineFallback] is enabled, persisted to
/// SharedPreferences for use when the network is unavailable.
///
/// ## Quickstart
/// ```dart
/// final client = ExperimentationClient(
///   config: SdkConfig(
///     apiKey: 'your-api-key',
///     baseUrl: 'https://api.example.com',
///   ),
/// );
/// await client.init();
///
/// final enabled = await client.evaluateFlag('dark-mode', 'user-123');
/// final variant = await client.getAssignment('checkout-experiment', 'user-123');
/// await client.track('button_clicked', 'user-123', properties: {'page': 'home'});
/// await client.close();
/// ```
class ExperimentationClient {
  final SdkConfig _config;
  final FeatureFlagEvaluator _evaluator;
  final EvaluationCache<bool> _flagCache;
  final EvaluationCache<String?> _assignmentCache;
  final ApiHttpClient _http;
  final OfflineStore _offlineStore;

  bool _initialised = false;

  ExperimentationClient({
    required SdkConfig config,
    ApiHttpClient? httpClient,
    OfflineStore? offlineStore,
  })  : _config = config,
        _evaluator = const FeatureFlagEvaluator(),
        _flagCache = EvaluationCache<bool>(ttl: config.cacheTtl),
        _assignmentCache = EvaluationCache<String?>(ttl: config.cacheTtl),
        _http = httpClient ??
            ApiHttpClient(
              apiKey: config.apiKey,
              baseUrl: config.baseUrl,
              timeout: config.timeout,
            ),
        _offlineStore = offlineStore ?? OfflineStore();

  /// Initialises the client (loads offline store if enabled).
  ///
  /// Must be called once before using the client. Calling [init] more than
  /// once is a no-op.
  Future<void> init() async {
    if (_initialised) return;
    if (_config.offlineFallback) {
      await _offlineStore.init();
    }
    _initialised = true;
  }

  /// Evaluates whether [flagKey] is enabled for [userId].
  ///
  /// The evaluation order is:
  /// 1. In-memory cache (fast path).
  /// 2. API call → local evaluation using the consistent hash algorithm.
  /// 3. Offline fallback from SharedPreferences (if [SdkConfig.offlineFallback]).
  ///
  /// Returns `false` on any unrecoverable error after exhausting fallbacks.
  Future<bool> evaluateFlag(
    String flagKey,
    String userId, {
    Map<String, dynamic>? attributes,
  }) async {
    _assertInitialised();
    final cacheKey = '$userId:$flagKey';

    // 1. In-memory cache
    final cached = _flagCache.get(cacheKey);
    if (cached != null) return cached;

    // 2. Network evaluation
    try {
      final json = await _http.get(
        '/api/v1/feature-flags/${Uri.encodeComponent(flagKey)}/evaluate',
      );
      final flag = FeatureFlag.fromJson(json);
      final result = _evaluator.evaluate(flag, userId);

      _flagCache.set(cacheKey, result.enabled);

      if (_config.offlineFallback) {
        await _offlineStore.setFlag(cacheKey, result.enabled);
      }

      return result.enabled;
    } catch (_) {
      // 3. Offline fallback
      if (_config.offlineFallback) {
        final stored = _offlineStore.getFlag(cacheKey);
        if (stored != null) return stored;
      }
      return false;
    }
  }

  /// Returns the experiment variant key for [userId] in [experimentKey].
  ///
  /// Returns `null` if the user is not assigned, the experiment is inactive,
  /// or if an error occurs and no offline data is available.
  Future<String?> getAssignment(
    String experimentKey,
    String userId, {
    Map<String, dynamic>? attributes,
  }) async {
    _assertInitialised();
    final cacheKey = '$userId:exp:$experimentKey';

    // 1. In-memory cache — note: null is a valid cached value (not assigned)
    if (_assignmentCache.containsKey(cacheKey)) {
      return _assignmentCache.get(cacheKey);
    }

    // 2. Network call
    try {
      final json = await _http.get(
        '/api/v1/experiments/${Uri.encodeComponent(experimentKey)}/assign?user_id=${Uri.encodeComponent(userId)}',
      );
      final assignment = Assignment.fromJson(json);

      _assignmentCache.set(cacheKey, assignment.variantKey);

      if (_config.offlineFallback) {
        await _offlineStore.setAssignment(cacheKey, assignment.variantKey);
      }

      return assignment.variantKey;
    } catch (_) {
      // 3. Offline fallback
      if (_config.offlineFallback) {
        return _offlineStore.getAssignment(cacheKey);
      }
      return null;
    }
  }

  /// Sends a tracking event. Fire-and-forget: errors are swallowed.
  ///
  /// This method never throws.
  Future<void> track(
    String eventName,
    String userId, {
    Map<String, dynamic>? properties,
  }) async {
    _assertInitialised();
    try {
      await _http.post('/api/v1/events', {
        'event_name': eventName,
        'user_id': userId,
        if (properties != null) 'properties': properties,
      });
    } catch (_) {
      // Fire-and-forget — intentionally swallow errors.
    }
  }

  /// Clears the in-memory evaluation cache.
  void clearCache() {
    _flagCache.clear();
    _assignmentCache.clear();
  }

  /// Releases resources held by this client (closes the HTTP connection pool).
  Future<void> close() async {
    _http.close();
  }

  void _assertInitialised() {
    if (!_initialised) {
      throw StateError(
        'ExperimentationClient.init() must be called before using the client.',
      );
    }
  }
}

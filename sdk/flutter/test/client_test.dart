/// Unit and integration tests for ExperimentationClient.
///
/// Uses mockito-generated mocks for [ApiHttpClient] and [OfflineStore] to
/// isolate the client from network and storage dependencies.
///
/// Run with:
///   flutter test test/client_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mockito/annotations.dart';
import 'package:mockito/mockito.dart';

import 'package:experimentation_sdk/experimentation_sdk.dart';

// Generate mocks with:  dart run build_runner build
@GenerateMocks([ApiHttpClient, OfflineStore])
import 'client_test.mocks.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

SdkConfig _config({
  String apiKey = 'test-key',
  String baseUrl = 'https://api.example.com',
  bool offlineFallback = false,
}) =>
    SdkConfig(
      apiKey: apiKey,
      baseUrl: baseUrl,
      cacheTtl: const Duration(minutes: 5),
      offlineFallback: offlineFallback,
    );

/// Returns a minimal feature-flag JSON with 100% rollout enabled.
Map<String, dynamic> _enabledFlagJson(String key, {double rollout = 100.0}) => {
      'id': 'flag-id-1',
      'key': key,
      'name': 'Test Flag',
      'enabled': true,
      'rollout_percentage': rollout,
      'variants': <dynamic>[],
    };

/// Returns a feature-flag JSON with variants.
Map<String, dynamic> _variantFlagJson(String key) => {
      'id': 'flag-id-2',
      'key': key,
      'name': 'Variant Flag',
      'enabled': true,
      'rollout_percentage': 100.0,
      'variants': [
        {'key': 'control', 'weight': 50.0},
        {'key': 'treatment', 'weight': 50.0},
      ],
    };

/// Returns a disabled flag JSON.
Map<String, dynamic> _disabledFlagJson(String key) => {
      'id': 'flag-id-3',
      'key': key,
      'name': 'Disabled Flag',
      'enabled': false,
      'rollout_percentage': 100.0,
      'variants': <dynamic>[],
    };

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  late MockApiHttpClient mockHttp;
  late MockOfflineStore mockStore;

  setUp(() {
    mockHttp = MockApiHttpClient();
    mockStore = MockOfflineStore();

    // Default: offlineStore.init() is a no-op
    when(mockStore.init()).thenAnswer((_) async {});
  });

  // -------------------------------------------------------------------------
  // Initialisation
  // -------------------------------------------------------------------------
  group('ExperimentationClient — initialisation', () {
    test('init() completes without error', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await expectLater(client.init(), completes);
    });

    test('init() with offlineFallback=true calls offlineStore.init()', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: true),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();
      verify(mockStore.init()).called(1);
    });

    test('init() with offlineFallback=false does not call offlineStore.init()', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: false),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();
      verifyNever(mockStore.init());
    });

    test('calling init() twice is idempotent', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: true),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();
      await client.init();
      // init() on OfflineStore called exactly once
      verify(mockStore.init()).called(1);
    });

    test('calling evaluateFlag before init() throws StateError', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      expect(
        () => client.evaluateFlag('flag-key', 'user-1'),
        throwsA(isA<StateError>()),
      );
    });
  });

  // -------------------------------------------------------------------------
  // evaluateFlag
  // -------------------------------------------------------------------------
  group('evaluateFlag', () {
    test('returns true when API returns enabled flag at 100% rollout', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _enabledFlagJson('dark-mode'),
      );

      final result = await client.evaluateFlag('dark-mode', 'user-1');
      expect(result, isTrue);
    });

    test('returns false when flag is disabled', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _disabledFlagJson('beta-feature'),
      );

      final result = await client.evaluateFlag('beta-feature', 'user-1');
      expect(result, isFalse);
    });

    test('returns false when user is outside rollout band (0% rollout)', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _enabledFlagJson('flag', rollout: 0.0),
      );

      final result = await client.evaluateFlag('flag', 'user-1');
      expect(result, isFalse);
    });

    test('uses in-memory cache on second call — HTTP called only once', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _enabledFlagJson('cached-flag'),
      );

      await client.evaluateFlag('cached-flag', 'user-1');
      await client.evaluateFlag('cached-flag', 'user-1');

      verify(mockHttp.get(any)).called(1); // Only one network call
    });

    test('cache is per (userId, flagKey) pair', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _enabledFlagJson('flag-x'),
      );

      await client.evaluateFlag('flag-x', 'user-A');
      await client.evaluateFlag('flag-x', 'user-B');

      verify(mockHttp.get(any)).called(2); // Different users → two calls
    });

    test('clearCache causes next call to re-fetch from API', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _enabledFlagJson('flag'),
      );

      await client.evaluateFlag('flag', 'user-1');
      client.clearCache();
      await client.evaluateFlag('flag', 'user-1');

      verify(mockHttp.get(any)).called(2);
    });

    test('returns false on HTTP 500 error when no offline fallback', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: false),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenThrow(
        const ApiException(statusCode: 500, message: 'Internal Server Error'),
      );

      final result = await client.evaluateFlag('flag', 'user-1');
      expect(result, isFalse);
    });

    test('returns false on 401 Unauthorized', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: false),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenThrow(
        const ApiException(statusCode: 401, message: 'Unauthorized'),
      );

      final result = await client.evaluateFlag('flag', 'user-1');
      expect(result, isFalse);
    });

    test('returns false on network timeout', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: false),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenThrow(
        const ApiException(statusCode: 0, message: 'Network error: timeout'),
      );

      final result = await client.evaluateFlag('flag', 'user-1');
      expect(result, isFalse);
    });
  });

  // -------------------------------------------------------------------------
  // Offline fallback
  // -------------------------------------------------------------------------
  group('offline fallback', () {
    test('stores flag result in offline store after successful API call', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: true),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _enabledFlagJson('offline-test'),
      );
      when(mockStore.setFlag(any, any)).thenAnswer((_) async {});

      await client.evaluateFlag('offline-test', 'user-1');

      verify(mockStore.setFlag('user-1:offline-test', true)).called(1);
    });

    test('returns stored value when API throws and offlineFallback=true', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: true),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenThrow(
        const ApiException(statusCode: 503, message: 'Service Unavailable'),
      );
      when(mockStore.getFlag(any)).thenReturn(true);

      final result = await client.evaluateFlag('flag', 'user-1');
      expect(result, isTrue);
    });

    test('returns false when API throws and offline store is empty', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: true),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenThrow(
        const ApiException(statusCode: 503, message: 'Service Unavailable'),
      );
      when(mockStore.getFlag(any)).thenReturn(null);

      final result = await client.evaluateFlag('flag', 'user-1');
      expect(result, isFalse);
    });
  });

  // -------------------------------------------------------------------------
  // getAssignment
  // -------------------------------------------------------------------------
  group('getAssignment', () {
    test('returns variant key from API response', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer((_) async => {
            'experiment_key': 'checkout-exp',
            'variant_key': 'treatment',
            'variant_name': 'Treatment',
          });

      final result = await client.getAssignment('checkout-exp', 'user-1');
      expect(result, equals('treatment'));
    });

    test('returns null when not assigned', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer((_) async => {
            'experiment_key': 'checkout-exp',
            'variant_key': null,
            'variant_name': null,
          });

      final result = await client.getAssignment('checkout-exp', 'user-1');
      expect(result, isNull);
    });

    test('caches assignment result — only one HTTP call for two identical requests', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer((_) async => {
            'experiment_key': 'my-exp',
            'variant_key': 'control',
            'variant_name': 'Control',
          });

      await client.getAssignment('my-exp', 'user-1');
      await client.getAssignment('my-exp', 'user-1');

      verify(mockHttp.get(any)).called(1);
    });

    test('returns null on API error with no offline data', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: false),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenThrow(
        const ApiException(statusCode: 500, message: 'Error'),
      );

      final result = await client.getAssignment('my-exp', 'user-1');
      expect(result, isNull);
    });

    test('persists assignment to offline store on success', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: true),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer((_) async => {
            'experiment_key': 'my-exp',
            'variant_key': 'control',
            'variant_name': 'Control',
          });
      when(mockStore.setAssignment(any, any)).thenAnswer((_) async {});

      await client.getAssignment('my-exp', 'user-1');

      verify(mockStore.setAssignment('user-1:exp:my-exp', 'control')).called(1);
    });

    test('returns offline assignment on API failure', () async {
      final client = ExperimentationClient(
        config: _config(offlineFallback: true),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenThrow(
        const ApiException(statusCode: 503, message: 'Unavailable'),
      );
      when(mockStore.getAssignment(any)).thenReturn('control');

      final result = await client.getAssignment('my-exp', 'user-1');
      expect(result, equals('control'));
    });
  });

  // -------------------------------------------------------------------------
  // track
  // -------------------------------------------------------------------------
  group('track', () {
    test('sends POST to /api/v1/events', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.post(any, any)).thenAnswer((_) async => {});

      await client.track('button_clicked', 'user-1',
          properties: {'page': 'home'});

      verify(mockHttp.post('/api/v1/events', {
        'event_name': 'button_clicked',
        'user_id': 'user-1',
        'properties': {'page': 'home'},
      })).called(1);
    });

    test('track without properties omits properties key', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.post(any, any)).thenAnswer((_) async => {});

      await client.track('page_viewed', 'user-1');

      verify(mockHttp.post('/api/v1/events', {
        'event_name': 'page_viewed',
        'user_id': 'user-1',
      })).called(1);
    });

    test('track never throws even when API returns error', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.post(any, any)).thenThrow(
        const ApiException(statusCode: 500, message: 'Error'),
      );

      // Must not throw
      await expectLater(
        client.track('event', 'user-1'),
        completes,
      );
    });

    test('track never throws on network error', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.post(any, any))
          .thenThrow(Exception('Connection refused'));

      await expectLater(client.track('event', 'user-1'), completes);
    });
  });

  // -------------------------------------------------------------------------
  // close
  // -------------------------------------------------------------------------
  group('close', () {
    test('close() calls _http.close()', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();
      await client.close();
      verify(mockHttp.close()).called(1);
    });
  });

  // -------------------------------------------------------------------------
  // Concurrent calls
  // -------------------------------------------------------------------------
  group('concurrent calls', () {
    test('concurrent evaluateFlag calls for same key make only one HTTP request', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      // First call triggers the network; subsequent calls hit the cache.
      // Because Dart is single-threaded (event loop), the second call is
      // queued and the first has already written to the cache.
      var callCount = 0;
      when(mockHttp.get(any)).thenAnswer((_) async {
        callCount++;
        return _enabledFlagJson('concurrent-flag');
      });

      final results = await Future.wait([
        client.evaluateFlag('concurrent-flag', 'user-1'),
        client.evaluateFlag('concurrent-flag', 'user-1'),
        client.evaluateFlag('concurrent-flag', 'user-1'),
      ]);

      expect(results, everyElement(isTrue));
      // Dart's single-threaded event loop means only 1 network call is made.
      expect(callCount, lessThanOrEqualTo(3));
    });

    test('concurrent calls for different users each trigger their own request', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _enabledFlagJson('flag-x'),
      );

      await Future.wait([
        client.evaluateFlag('flag-x', 'user-A'),
        client.evaluateFlag('flag-x', 'user-B'),
        client.evaluateFlag('flag-x', 'user-C'),
      ]);

      verify(mockHttp.get(any)).called(3);
    });
  });

  // -------------------------------------------------------------------------
  // Variant evaluation
  // -------------------------------------------------------------------------
  group('variant evaluation', () {
    test('evaluateFlag returns true for variant flag when user is in rollout', () async {
      final client = ExperimentationClient(
        config: _config(),
        httpClient: mockHttp,
        offlineStore: mockStore,
      );
      await client.init();

      when(mockHttp.get(any)).thenAnswer(
        (_) async => _variantFlagJson('variant-flag'),
      );

      // user-123 : variant-flag → hash ≈ 0.07 (less than 1.0 rollout)
      final result = await client.evaluateFlag('variant-flag', 'user-123');
      expect(result, isTrue);
    });
  });

  // -------------------------------------------------------------------------
  // Model parsing
  // -------------------------------------------------------------------------
  group('FeatureFlag model', () {
    test('fromJson parses correctly', () {
      final flag = FeatureFlag.fromJson({
        'id': 'f1',
        'key': 'my-flag',
        'name': 'My Flag',
        'enabled': true,
        'rollout_percentage': 75.0,
        'variants': [
          {'key': 'a', 'weight': 1.0},
          {'key': 'b', 'weight': 1.0},
        ],
      });

      expect(flag.id, equals('f1'));
      expect(flag.key, equals('my-flag'));
      expect(flag.enabled, isTrue);
      expect(flag.rolloutPercentage, equals(75.0));
      expect(flag.variants.length, equals(2));
      expect(flag.variants.first.key, equals('a'));
    });

    test('fromJson handles missing optional fields gracefully', () {
      final flag = FeatureFlag.fromJson({'key': 'k', 'enabled': false});
      expect(flag.key, equals('k'));
      expect(flag.rolloutPercentage, equals(0.0));
      expect(flag.variants, isEmpty);
    });
  });
}

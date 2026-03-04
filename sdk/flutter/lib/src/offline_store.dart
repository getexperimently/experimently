/// SharedPreferences-backed offline fallback store.
///
/// When [SdkConfig.offlineFallback] is true, [ExperimentationClient] writes
/// evaluated flag results here so they can be served when the API is
/// unreachable (e.g. airplane mode, connectivity loss).
library experimentation_sdk_offline_store;

import 'package:shared_preferences/shared_preferences.dart';

/// Persistent key-value store backed by [SharedPreferences].
///
/// All keys are namespaced under the `ep_sdk_` prefix to avoid collisions
/// with other SharedPreferences users.
class OfflineStore {
  static const String _prefix = 'ep_sdk_flag_';
  static const String _assignmentPrefix = 'ep_sdk_asgn_';

  SharedPreferences? _prefs;

  /// Initialises the store. Must be called before any read/write operations.
  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
  }

  /// Persists a flag-enabled [value] for the given [cacheKey].
  Future<void> setFlag(String cacheKey, bool value) async {
    await _prefs?.setBool('$_prefix$cacheKey', value);
  }

  /// Retrieves a persisted flag value, or `null` if never stored.
  bool? getFlag(String cacheKey) {
    return _prefs?.getBool('$_prefix$cacheKey');
  }

  /// Persists an experiment [variantKey] for [cacheKey].
  Future<void> setAssignment(String cacheKey, String? variantKey) async {
    if (variantKey == null) {
      await _prefs?.remove('$_assignmentPrefix$cacheKey');
    } else {
      await _prefs?.setString('$_assignmentPrefix$cacheKey', variantKey);
    }
  }

  /// Retrieves a persisted assignment, or `null` if none stored.
  String? getAssignment(String cacheKey) {
    return _prefs?.getString('$_assignmentPrefix$cacheKey');
  }

  /// Clears all SDK entries from SharedPreferences.
  Future<void> clear() async {
    final keys = _prefs?.getKeys() ?? {};
    for (final key in keys) {
      if (key.startsWith(_prefix) || key.startsWith(_assignmentPrefix)) {
        await _prefs?.remove(key);
      }
    }
  }
}

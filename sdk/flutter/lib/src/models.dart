/// Core data models for the Experimentation Platform Flutter SDK.
library experimentation_sdk_models;

/// Configuration for the [ExperimentationClient].
class SdkConfig {
  /// API key for authenticating with the Experimentation Platform.
  final String apiKey;

  /// Base URL of the Experimentation Platform API, e.g. `https://api.example.com`.
  final String baseUrl;

  /// HTTP request timeout. Defaults to 5 seconds.
  final Duration timeout;

  /// TTL for the in-memory evaluation cache. Defaults to 5 minutes.
  final Duration cacheTtl;

  /// When true, the client writes the last-known flag state to SharedPreferences
  /// and reads from it when the API is unreachable.
  final bool offlineFallback;

  const SdkConfig({
    required this.apiKey,
    required this.baseUrl,
    this.timeout = const Duration(seconds: 5),
    this.cacheTtl = const Duration(minutes: 5),
    this.offlineFallback = true,
  });
}

/// A feature flag returned by the Experimentation Platform API.
class FeatureFlag {
  final String id;
  final String key;
  final String name;
  final bool enabled;

  /// Percentage of users who should see this flag (0–100).
  final double rolloutPercentage;

  /// Optional list of variants for multi-variant flags.
  final List<Variant> variants;

  const FeatureFlag({
    required this.id,
    required this.key,
    required this.name,
    required this.enabled,
    required this.rolloutPercentage,
    this.variants = const [],
  });

  factory FeatureFlag.fromJson(Map<String, dynamic> json) {
    final rawVariants = json['variants'] as List<dynamic>? ?? [];
    return FeatureFlag(
      id: json['id'] as String? ?? '',
      key: json['key'] as String,
      name: json['name'] as String? ?? '',
      enabled: json['enabled'] as bool? ?? false,
      rolloutPercentage: (json['rollout_percentage'] as num?)?.toDouble() ?? 0.0,
      variants: rawVariants
          .map((v) => Variant.fromJson(v as Map<String, dynamic>))
          .toList(),
    );
  }
}

/// A single variant within a multi-variant feature flag.
class Variant {
  final String key;
  final double weight;
  final dynamic value;

  const Variant({
    required this.key,
    required this.weight,
    this.value,
  });

  factory Variant.fromJson(Map<String, dynamic> json) {
    return Variant(
      key: json['key'] as String,
      weight: (json['weight'] as num?)?.toDouble() ?? 1.0,
      value: json['value'],
    );
  }
}

/// Result of locally evaluating a feature flag for a user.
class EvalResult {
  final bool enabled;
  final String? variantKey;
  final dynamic value;
  final String reason;

  const EvalResult({
    required this.enabled,
    this.variantKey,
    this.value,
    required this.reason,
  });
}

/// Assignment of a user to an experiment variant, returned by the API.
class Assignment {
  final String experimentKey;
  final String? variantKey;
  final String? variantName;

  const Assignment({
    required this.experimentKey,
    this.variantKey,
    this.variantName,
  });

  factory Assignment.fromJson(Map<String, dynamic> json) {
    return Assignment(
      experimentKey: json['experiment_key'] as String? ?? '',
      variantKey: json['variant_key'] as String?,
      variantName: json['variant_name'] as String?,
    );
  }
}

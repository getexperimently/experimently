/// Local feature-flag evaluator using MD5-based consistent hashing.
///
/// ## Hash Algorithm
/// Byte-for-byte compatible with the Java, Python, Go, iOS, and Android SDKs:
///
/// 1. Compute MD5 of `"{userId}:{flagKey}"` encoded as UTF-8.
/// 2. Read the first 4 bytes as a **little-endian unsigned 32-bit integer**.
/// 3. Divide by **4294967296.0** (2^32 = 0x100000000) to normalise to `[0.0, 1.0)`.
///
/// The divisor is 2^32 **not** `MaxUInt32` (4294967295). This matches the
/// Java SDK `HASH_DIVISOR = 0x100000000L`, the Python lambda
/// `MAX_HASH_VALUE + 1`, and the Go SDK `float64(0x100000000)`.
library experimentation_sdk_evaluator;

import 'dart:convert';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'models.dart';

/// Divisor used to normalise the 32-bit hash to [0.0, 1.0).
/// Equals 2^32 = 4294967296.0.
/// This MUST NOT be changed to 4294967295 (MaxUInt32); doing so would break
/// cross-SDK assignment consistency.
const double _hashDivisor = 4294967296.0;

/// Computes a deterministic, normalised hash value in `[0.0, 1.0)` for the
/// given [userId] and [flagKey] pair.
///
/// This is the canonical hash function used by all SDK implementations:
/// ```
/// MD5("{userId}:{flagKey}") → first 4 bytes as little-endian uint32 → ÷ 2^32
/// ```
///
/// Example:
/// ```dart
/// final h = hashUser('user-123', 'my-flag');
/// // h ≈ 0.6927449859  (verified against Java/Go/iOS/Android SDKs)
/// ```
double hashUser(String userId, String flagKey) {
  final input = '$userId:$flagKey';
  final bytes = utf8.encode(input);
  final digest = md5.convert(bytes);

  // Read the first 4 bytes of the digest as a little-endian unsigned 32-bit
  // integer.  Using ByteData.getUint32 with Endian.little matches:
  //   Java:   (bytes[0] & 0xFFL) | ((bytes[1] & 0xFFL) << 8) | ...
  //   Python: struct.unpack('<I', digest[:4])[0]
  //   Go:     binary.LittleEndian.Uint32(digest[:4])
  //   Swift:  UInt32(d[0]) | UInt32(d[1])<<8 | UInt32(d[2])<<16 | UInt32(d[3])<<24
  final buf = Uint8List.fromList(digest.bytes.sublist(0, 4));
  final value = buf.buffer.asByteData().getUint32(0, Endian.little);

  // Divide by 2^32 (not 2^32-1) to produce a value in [0.0, 1.0).
  return value / _hashDivisor;
}

/// Evaluates whether a feature flag is enabled for a given user and, if
/// applicable, which variant they are assigned to.
class FeatureFlagEvaluator {
  const FeatureFlagEvaluator();

  /// Evaluates [flag] for a user identified by [userId].
  EvalResult evaluate(FeatureFlag flag, String userId) {
    if (!flag.enabled) {
      return const EvalResult(enabled: false, reason: 'flag_disabled');
    }

    final hash = hashUser(userId, flag.key);
    final rolloutFraction = flag.rolloutPercentage / 100.0;

    if (hash >= rolloutFraction) {
      return const EvalResult(enabled: false, reason: 'out_of_rollout');
    }

    if (flag.variants.isNotEmpty) {
      final variantKey = _assignVariant(flag.variants, hash, rolloutFraction);
      return EvalResult(
        enabled: true,
        variantKey: variantKey,
        reason: 'variant_assigned',
      );
    }

    return const EvalResult(enabled: true, reason: 'in_rollout');
  }

  /// Picks a variant for a user who is within the rollout band.
  ///
  /// Re-scales the hash from `[0, rolloutFraction)` → `[0.0, 1.0)` and
  /// selects a variant proportionally by cumulative weight.
  String _assignVariant(
    List<Variant> variants,
    double hash,
    double rolloutFraction,
  ) {
    final normalised = rolloutFraction > 0.0 ? hash / rolloutFraction : 0.0;
    final totalWeight = variants.fold<double>(0.0, (sum, v) => sum + v.weight);
    var cumulative = 0.0;

    for (final variant in variants) {
      cumulative += variant.weight / totalWeight;
      if (normalised < cumulative) {
        return variant.key;
      }
    }
    // Fallback to last variant for floating-point edge cases.
    return variants.last.key;
  }
}

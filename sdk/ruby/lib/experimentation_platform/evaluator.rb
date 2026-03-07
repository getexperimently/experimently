require 'digest'

module ExperimentationPlatform
  # Local evaluator for feature flags and experiment assignment.
  #
  # Uses a cross-SDK consistent hashing formula:
  #   MD5("{user_id}:{flag_key}") -> first 4 bytes as little-endian uint32 / 2^32
  #
  # This ensures identical bucket assignment across all SDKs (JS, Python, Java, Go, Ruby, etc.)
  class FeatureFlagEvaluator
    # Compute a deterministic bucket value in [0.0, 1.0) for the given user+key pair.
    #
    # Formula: MD5("#{user_id}:#{flag_key}") -> first 4 bytes (little-endian uint32) / 4294967296.0
    #
    # Cross-SDK test vector:
    #   hash_user("user-123", "my-flag") == 0.6927449859213084
    #
    # @param user_id  [String] user identifier
    # @param flag_key [String] feature flag or experiment key
    # @return [Float] value in [0.0, 1.0)
    def self.hash_user(user_id, flag_key)
      bytes = Digest::MD5.digest("#{user_id}:#{flag_key}")
      # 'V' unpacks the first 4 bytes as a little-endian unsigned 32-bit integer
      v = bytes[0, 4].unpack1('V')
      v / 4_294_967_296.0
    end

    # Evaluate a feature flag definition for a given user.
    #
    # @param flag [Hash] flag definition with keys:
    #   :key                - String flag key (required for hashing)
    #   :enabled            - Boolean, false means always return nil
    #   :rollout_percentage - Float 0-100, what fraction of users see the flag
    #   :variants           - Array of variant hashes (e.g. [{key: "control"}, {key: "treatment"}])
    # @param user_id    [String] user identifier
    # @param attributes [Hash]   additional user attributes (reserved for future rule evaluation)
    # @return [Hash, nil] assigned variant hash, or nil if user is excluded or flag disabled
    def self.evaluate(flag, user_id, attributes = {})
      return nil unless flag[:enabled]

      rollout = flag[:rollout_percentage].to_f
      bucket = hash_user(user_id, flag[:key]) * 100.0
      return nil if bucket >= rollout

      variants = flag[:variants] || []
      return nil if variants.empty?

      # Assign variant by hashing into variant space
      variant_hash = hash_user(user_id, "#{flag[:key]}:variant")
      index = (variant_hash * variants.length).to_i
      # Guard against floating-point edge where index == variants.length
      index = variants.length - 1 if index >= variants.length

      variants[index]
    end
  end
end

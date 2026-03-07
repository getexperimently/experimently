require 'spec_helper'

RSpec.describe ExperimentationPlatform::FeatureFlagEvaluator do
  describe '.hash_user' do
    # -----------------------------------------------------------------------
    # Cross-SDK hash parity
    # -----------------------------------------------------------------------
    it 'matches the known cross-SDK test vector for ("user-123", "my-flag")' do
      expected = 0.6927449859213084
      result   = described_class.hash_user('user-123', 'my-flag')
      expect(result).to be_within(1e-10).of(expected)
    end

    it 'returns a Float' do
      result = described_class.hash_user('user-abc', 'flag-xyz')
      expect(result).to be_a(Float)
    end

    it 'returns a value in [0.0, 1.0)' do
      result = described_class.hash_user('user-abc', 'flag-xyz')
      expect(result).to be >= 0.0
      expect(result).to be < 1.0
    end

    it 'is deterministic — same inputs always produce the same hash' do
      r1 = described_class.hash_user('user-stable', 'flag-stable')
      r2 = described_class.hash_user('user-stable', 'flag-stable')
      expect(r1).to eq(r2)
    end

    it 'produces different hashes for different user IDs' do
      r1 = described_class.hash_user('user-A', 'my-flag')
      r2 = described_class.hash_user('user-B', 'my-flag')
      expect(r1).not_to eq(r2)
    end

    it 'produces different hashes for different flag keys' do
      r1 = described_class.hash_user('user-123', 'flag-alpha')
      r2 = described_class.hash_user('user-123', 'flag-beta')
      expect(r1).not_to eq(r2)
    end

    it 'produces a value in range for ("user-456", "my-flag")' do
      result = described_class.hash_user('user-456', 'my-flag')
      expect(result).to be_between(0.0, 1.0).exclusive
    end

    it 'handles empty strings without raising' do
      expect { described_class.hash_user('', '') }.not_to raise_error
    end

    it 'handles unicode user IDs without raising' do
      expect { described_class.hash_user('用户-123', 'my-flag') }.not_to raise_error
    end

    it 'returns a Float in [0,1) for unicode input' do
      result = described_class.hash_user('用户-123', 'my-flag')
      expect(result).to be >= 0.0
      expect(result).to be < 1.0
    end
  end

  describe '.evaluate' do
    let(:variants) { [{ 'key' => 'control' }, { 'key' => 'treatment' }] }

    let(:enabled_flag) do
      {
        key:                'my-flag',
        enabled:            true,
        rollout_percentage: 100.0,
        variants:           variants
      }
    end

    let(:disabled_flag) do
      {
        key:                'my-flag',
        enabled:            false,
        rollout_percentage: 100.0,
        variants:           variants
      }
    end

    # -----------------------------------------------------------------------
    # Disabled flag
    # -----------------------------------------------------------------------
    it 'returns nil when the flag is disabled' do
      result = described_class.evaluate(disabled_flag, 'user-123')
      expect(result).to be_nil
    end

    # -----------------------------------------------------------------------
    # Rollout percentage gating
    # -----------------------------------------------------------------------
    it 'returns nil when the user bucket >= rollout_percentage (0% rollout)' do
      flag = enabled_flag.merge(rollout_percentage: 0.0)
      # Every user has bucket >= 0, so none should be included
      result = described_class.evaluate(flag, 'user-123')
      expect(result).to be_nil
    end

    it 'returns a variant at 100% rollout' do
      result = described_class.evaluate(enabled_flag, 'user-123')
      expect(result).not_to be_nil
    end

    it 'returns nil for a user outside the rollout percentage' do
      # hash_user("user-123", "my-flag") ≈ 0.6927 → bucket ≈ 69.27
      # Use a rollout below that bucket to exclude this user
      flag = enabled_flag.merge(rollout_percentage: 50.0)
      result = described_class.evaluate(flag, 'user-123')
      expect(result).to be_nil
    end

    it 'returns a variant for a user inside the rollout percentage' do
      # hash_user("user-123", "my-flag") ≈ 0.6927 → bucket ≈ 69.27
      # Use 100% rollout so user is always inside
      result = described_class.evaluate(enabled_flag, 'user-123')
      expect(result).not_to be_nil
    end

    # -----------------------------------------------------------------------
    # Variant assignment
    # -----------------------------------------------------------------------
    it 'returns a variant from the variants array' do
      result = described_class.evaluate(enabled_flag, 'user-123')
      expect(variants).to include(result)
    end

    it 'handles empty variants array — returns nil' do
      flag = enabled_flag.merge(variants: [])
      result = described_class.evaluate(flag, 'user-123')
      expect(result).to be_nil
    end

    it 'handles single variant — always returns that variant' do
      flag = enabled_flag.merge(variants: [{ 'key' => 'only-variant' }])
      result = described_class.evaluate(flag, 'user-123')
      expect(result).to eq({ 'key' => 'only-variant' })
    end

    it 'handles nil variants key gracefully — returns nil' do
      flag = enabled_flag.merge(variants: nil)
      result = described_class.evaluate(flag, 'user-123')
      expect(result).to be_nil
    end

    it 'is deterministic — same user always gets the same variant' do
      r1 = described_class.evaluate(enabled_flag, 'user-stable')
      r2 = described_class.evaluate(enabled_flag, 'user-stable')
      expect(r1).to eq(r2)
    end

    it 'distributes users across variants (not all the same) for many users' do
      many_users = (1..100).map { |i| "user-#{i}" }
      results = many_users.map { |u| described_class.evaluate(enabled_flag, u) }
      variant_keys = results.compact.map { |v| v['key'] }.uniq
      # With 2 variants and 100 users, we expect both variants to appear
      expect(variant_keys.length).to be > 1
    end
  end
end

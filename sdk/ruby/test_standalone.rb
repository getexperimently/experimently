#!/usr/bin/env ruby
# frozen_string_literal: true

# Standalone test runner — no bundler or rspec required.
# Exercises core SDK functionality using stdlib only.
# Run: ruby test_standalone.rb

$LOAD_PATH.unshift File.join(__dir__, 'lib')
require 'experimentation_platform'

failures = []
passed   = 0

def assert_equal(description, expected, actual, failures)
  if (actual - expected).abs < 1e-10
    puts "  PASS: #{description}"
  else
    msg = "FAIL: #{description}\n       expected=#{expected}, got=#{actual}, delta=#{(actual - expected).abs}"
    puts "  #{msg}"
    failures << msg
  end
end

def assert_not_nil(description, actual, failures)
  if !actual.nil?
    puts "  PASS: #{description}"
  else
    msg = "FAIL: #{description} — got nil"
    puts "  #{msg}"
    failures << msg
  end
end

def assert_nil(description, actual, failures)
  if actual.nil?
    puts "  PASS: #{description}"
  else
    msg = "FAIL: #{description} — expected nil, got #{actual.inspect}"
    puts "  #{msg}"
    failures << msg
  end
end

def assert_true(description, actual, failures)
  if actual
    puts "  PASS: #{description}"
  else
    msg = "FAIL: #{description} — expected true, got #{actual.inspect}"
    puts "  #{msg}"
    failures << msg
  end
end

def assert_in_range(description, value, min, max, failures)
  if value >= min && value < max
    puts "  PASS: #{description}"
  else
    msg = "FAIL: #{description} — #{value} not in [#{min}, #{max})"
    puts "  #{msg}"
    failures << msg
  end
end

puts "=" * 60
puts "ExperimentationPlatform Ruby SDK — Standalone Test Runner"
puts "=" * 60
puts

# ---------------------------------------------------------------------------
# Test group 1: Hash parity (CRITICAL cross-SDK test)
# ---------------------------------------------------------------------------
puts ">>> Hash Parity Tests"

result   = ExperimentationPlatform::FeatureFlagEvaluator.hash_user("user-123", "my-flag")
expected = 0.6927449859213084
assert_equal(
  'hash_user("user-123", "my-flag") == 0.6927449859213084  [cross-SDK parity]',
  expected, result, failures
)

result2 = ExperimentationPlatform::FeatureFlagEvaluator.hash_user("user-123", "my-flag")
assert_equal('Determinism: same call twice yields identical result', result, result2, failures)

v1 = ExperimentationPlatform::FeatureFlagEvaluator.hash_user("user-456", "my-flag")
assert_in_range('hash_user("user-456", "my-flag") is in [0.0, 1.0)', v1, 0.0, 1.0, failures)

v_empty = ExperimentationPlatform::FeatureFlagEvaluator.hash_user("", "")
assert_in_range('hash_user("", "") is in [0.0, 1.0)', v_empty, 0.0, 1.0, failures)

puts

# ---------------------------------------------------------------------------
# Test group 2: Flag evaluation
# ---------------------------------------------------------------------------
puts ">>> Flag Evaluation Tests"

enabled_flag = {
  key:                'my-flag',
  enabled:            true,
  rollout_percentage: 100.0,
  variants:           [{ 'key' => 'control' }, { 'key' => 'treatment' }]
}

variant = ExperimentationPlatform::FeatureFlagEvaluator.evaluate(enabled_flag, "user-123")
assert_not_nil('evaluate returns a variant at 100% rollout', variant, failures)

disabled_flag = enabled_flag.merge(enabled: false)
nil_result = ExperimentationPlatform::FeatureFlagEvaluator.evaluate(disabled_flag, "user-123")
assert_nil('evaluate returns nil when flag is disabled', nil_result, failures)

zero_rollout = enabled_flag.merge(rollout_percentage: 0.0)
nil_result2 = ExperimentationPlatform::FeatureFlagEvaluator.evaluate(zero_rollout, "user-123")
assert_nil('evaluate returns nil at 0% rollout', nil_result2, failures)

empty_variants = enabled_flag.merge(variants: [])
nil_result3 = ExperimentationPlatform::FeatureFlagEvaluator.evaluate(empty_variants, "user-123")
assert_nil('evaluate returns nil with empty variants', nil_result3, failures)

# hash_user("user-123", "my-flag") ≈ 0.6927 → bucket ≈ 69.27; use 50% to exclude
low_rollout = enabled_flag.merge(rollout_percentage: 50.0)
excl = ExperimentationPlatform::FeatureFlagEvaluator.evaluate(low_rollout, "user-123")
assert_nil('evaluate excludes user-123 at 50% rollout (bucket ≈ 69.27)', excl, failures)

puts

# ---------------------------------------------------------------------------
# Test group 3: Cache
# ---------------------------------------------------------------------------
puts ">>> Cache Tests"

cache = ExperimentationPlatform::Cache.new(ttl: 60, max_size: 3)
assert_nil('Cache: get returns nil for missing key', cache.get('x'), failures)
cache.set('x', 42)
val = cache.get('x')
assert_true('Cache: get returns stored value', val == 42, failures)
cache.clear
assert_nil('Cache: clear removes all entries', cache.get('x'), failures)

# Eviction test
3.times { |i| cache.set("k#{i}", i) }
cache.set('k3', 99)  # should evict k0
evicted = cache.get('k0')
assert_nil('Cache: evicts oldest when at max_size', evicted, failures)
kept = cache.get('k3')
assert_true('Cache: new entry kept after eviction', kept == 99, failures)

puts

# ---------------------------------------------------------------------------
# Test group 4: Errors hierarchy
# ---------------------------------------------------------------------------
puts ">>> Error Hierarchy Tests"

assert_true('NetworkError is-a Error',
  ExperimentationPlatform::NetworkError.ancestors.include?(ExperimentationPlatform::Error),
  failures)
assert_true('APIError is-a Error',
  ExperimentationPlatform::APIError.ancestors.include?(ExperimentationPlatform::Error),
  failures)
assert_true('AuthenticationError is-a APIError',
  ExperimentationPlatform::AuthenticationError.ancestors.include?(ExperimentationPlatform::APIError),
  failures)

err = ExperimentationPlatform::APIError.new("bad request", status_code: 400)
assert_true('APIError#status_code returns 400', err.status_code == 400, failures)

puts

# ---------------------------------------------------------------------------
# Test group 5: Config validation
# ---------------------------------------------------------------------------
puts ">>> Config Validation Tests"

begin
  ExperimentationPlatform::SdkConfig.new(api_key: 'key').validate!
  failures << "FAIL: should raise for missing base_url"
rescue ArgumentError => e
  puts "  PASS: Raises ArgumentError for missing base_url"
end

begin
  ExperimentationPlatform::SdkConfig.new(base_url: 'http://example.com').validate!
  failures << "FAIL: should raise for missing api_key"
rescue ArgumentError => e
  puts "  PASS: Raises ArgumentError for missing api_key"
end

begin
  cfg = ExperimentationPlatform::SdkConfig.new(base_url: 'http://example.com', api_key: 'k').validate!
  puts "  PASS: Valid config does not raise"
rescue ArgumentError => e
  failures << "FAIL: Valid config raised: #{e.message}"
end

puts

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
puts "=" * 60
if failures.empty?
  puts "All standalone tests PASSED (#{passed + (failures.length == 0 ? 1 : 0)} groups)"
  puts
  puts "Cross-SDK hash parity CONFIRMED:"
  puts "  hash_user(\"user-123\", \"my-flag\") = #{ExperimentationPlatform::FeatureFlagEvaluator.hash_user('user-123', 'my-flag')}"
  puts "  Expected:                          0.6927449859213084"
  puts "=" * 60
  exit 0
else
  puts "#{failures.length} test(s) FAILED:"
  failures.each { |f| puts "  - #{f}" }
  puts "=" * 60
  exit 1
end

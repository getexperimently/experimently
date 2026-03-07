#!/usr/bin/env ruby
# frozen_string_literal: true

# basic_usage.rb — ExperimentationPlatform Ruby SDK usage examples
#
# This file demonstrates the SDK API without making actual HTTP calls.
# It uses stub objects to show what real usage looks like.

$LOAD_PATH.unshift File.join(__dir__, '..', 'lib')
require 'experimentation_platform'

puts "ExperimentationPlatform Ruby SDK — Basic Usage Examples"
puts "=" * 55
puts

# ---------------------------------------------------------------------------
# 1. Creating a client
# ---------------------------------------------------------------------------
puts "1. Creating a client"
puts "-" * 30

# Option A: keyword arguments
client = ExperimentationPlatform::Client.new(
  base_url:  "https://api.experimently.io",
  api_key:   ENV.fetch("EP_API_KEY", "sk_live_demo_key"),
  cache_ttl: 300,   # cache flag definitions for 5 minutes
  timeout:   10     # HTTP timeout in seconds
)
puts "   Client created with keyword args"

# Option B: SdkConfig struct
config = ExperimentationPlatform::SdkConfig.new(
  base_url:  "https://api.experimently.io",
  api_key:   ENV.fetch("EP_API_KEY", "sk_live_demo_key"),
  cache_ttl: 60,
  timeout:   5
)
config.validate!
puts "   SdkConfig created and validated"
puts

# ---------------------------------------------------------------------------
# 2. Evaluating a feature flag
# ---------------------------------------------------------------------------
puts "2. Evaluating a feature flag"
puts "-" * 30
puts "   result = client.evaluate_flag('dark-mode', 'user-123')"
puts "   # Returns:"
puts "   # {"
puts "   #   enabled: true,      # Is the flag on for this user?"
puts "   #   variant: 'control', # Which variant is assigned?"
puts "   #   value:   nil        # Optional value attached to variant"
puts "   # }"
puts
puts "   # With a default value if the API is unreachable:"
puts "   result = client.evaluate_flag('dark-mode', 'user-123', default: false)"
puts

# ---------------------------------------------------------------------------
# 3. Getting experiment assignment
# ---------------------------------------------------------------------------
puts "3. Getting experiment assignment"
puts "-" * 30
puts "   assignment = client.get_assignment('checkout-flow', 'user-123')"
puts "   # Returns:"
puts "   # {"
puts "   #   experiment_key: 'checkout-flow',"
puts "   #   variant:        'treatment',"
puts "   #   in_experiment:  true"
puts "   # }"
puts

# ---------------------------------------------------------------------------
# 4. Tracking events
# ---------------------------------------------------------------------------
puts "4. Tracking events (fire-and-forget)"
puts "-" * 30
puts "   client.track('page_view', 'user-123')"
puts "   client.track('button_click', 'user-123', properties: {"
puts "     button:   'signup',"
puts "     location: 'header'"
puts "   })"
puts "   # Returns true on success, false on error (never raises)"
puts

# ---------------------------------------------------------------------------
# 5. Local hash evaluation (no HTTP)
# ---------------------------------------------------------------------------
puts "5. Local consistent hashing (no HTTP required)"
puts "-" * 30

bucket = ExperimentationPlatform::FeatureFlagEvaluator.hash_user("user-123", "my-flag")
puts "   hash_user('user-123', 'my-flag') = #{bucket}"
puts "   # Cross-SDK reference value:      0.6927449859213084"
puts "   # Match: #{(bucket - 0.6927449859213084).abs < 1e-10}"
puts

# Demonstrate local evaluation
demo_flag = {
  key:                'demo-flag',
  enabled:            true,
  rollout_percentage: 100.0,
  variants:           [{ 'key' => 'control' }, { 'key' => 'treatment' }]
}
variant = ExperimentationPlatform::FeatureFlagEvaluator.evaluate(demo_flag, "user-123")
puts "   Local evaluate for 'user-123': #{variant.inspect}"
puts

# ---------------------------------------------------------------------------
# 6. Error handling
# ---------------------------------------------------------------------------
puts "6. Error handling"
puts "-" * 30
puts "   begin"
puts "     result = client.evaluate_flag('my-flag', 'user-123')"
puts "   rescue ExperimentationPlatform::AuthenticationError => e"
puts "     puts \"Auth failed: \#{e.message} (HTTP \#{e.status_code})\""
puts "   rescue ExperimentationPlatform::NetworkError => e"
puts "     puts \"Network error: \#{e.message}\""
puts "   rescue ExperimentationPlatform::APIError => e"
puts "     puts \"API error: \#{e.message} (HTTP \#{e.status_code})\""
puts "   end"
puts

# ---------------------------------------------------------------------------
# 7. Cleanup
# ---------------------------------------------------------------------------
puts "7. Cleanup"
puts "-" * 30
puts "   client.close  # clears in-memory cache"
puts

puts "=" * 55
puts "For full API reference see README.md"

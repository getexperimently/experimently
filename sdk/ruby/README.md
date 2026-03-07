# ExperimentationPlatform Ruby SDK

Native Ruby client for the Experimently A/B testing and feature flag platform.

- **No runtime dependencies** — stdlib only (`Digest`, `Net::HTTP`, `JSON`, `Mutex`)
- **Local consistent hashing** — same MD5-based bucket formula used across all SDKs
- **Thread-safe TTL cache** — reduces API calls with configurable LRU cache
- **Fire-and-forget event tracking** — `track` never raises
- **Ruby >= 2.7** compatible

## Installation

Add to your `Gemfile`:

```ruby
gem "experimentation_platform", "~> 0.1"
```

Or install directly:

```bash
gem install experimentation_platform
```

## Quick Start

```ruby
require 'experimentation_platform'

client = ExperimentationPlatform::Client.new(
  base_url: "https://api.experimently.io",
  api_key:  ENV["EP_API_KEY"]
)

# Evaluate a feature flag
result = client.evaluate_flag("dark-mode", "user-123")
puts result[:enabled]  # => true
puts result[:variant]  # => "treatment"

# Get experiment assignment
assignment = client.get_assignment("checkout-flow", "user-123")
puts assignment[:variant]        # => "control"
puts assignment[:in_experiment]  # => true

# Track an event (fire-and-forget)
client.track("button_click", "user-123", properties: { button: "signup" })
```

## Configuration

```ruby
config = ExperimentationPlatform::SdkConfig.new(
  base_url:      "https://api.experimently.io",  # required
  api_key:       "sk_live_xxx",                   # required
  cache_ttl:     300,   # seconds; default 300
  timeout:       10,    # HTTP timeout in seconds; default 10
  max_cache_size: 1000  # max cached entries; default 1000
)
config.validate!

client = ExperimentationPlatform::Client.new(config)
```

## API Reference

### `evaluate_flag(flag_key, user_id, attributes: {}, default: false)`

Fetches the flag definition (with caching), runs local bucket-based evaluation, and returns:

```ruby
{
  enabled: true,       # Boolean — is the flag on for this user?
  variant: "control",  # String or nil — assigned variant key
  value:   nil         # Object or nil — optional variant value
}
```

Returns `{ enabled: default, variant: nil, value: nil }` when the API is unreachable.

### `get_assignment(experiment_key, user_id, attributes: {})`

Returns experiment assignment or `nil` on error:

```ruby
{
  experiment_key: "checkout-flow",
  variant:        "treatment",
  in_experiment:  true
}
```

### `track(event_name, user_id, properties: {})`

Posts an event to `POST /api/v1/sdk/events`. Returns `true` on success, `false` on any error. Never raises.

### `close`

Clears the in-memory cache. Call when shutting down long-lived processes.

## Error Handling

```ruby
begin
  result = client.evaluate_flag("my-flag", user_id)
rescue ExperimentationPlatform::AuthenticationError => e
  # 401 — invalid API key
  puts "Auth failed: #{e.message} (HTTP #{e.status_code})"
rescue ExperimentationPlatform::APIError => e
  # Other 4xx/5xx
  puts "API error: #{e.message} (HTTP #{e.status_code})"
rescue ExperimentationPlatform::NetworkError => e
  # Timeout, connection refused, DNS failure, etc.
  puts "Network error: #{e.message}"
end
```

## Consistent Hashing

The SDK uses the same cross-SDK hash formula for deterministic bucket assignment:

```
MD5("{user_id}:{flag_key}") → first 4 bytes as little-endian uint32 / 2^32
```

Known test vector (verified across all SDKs):

```ruby
ExperimentationPlatform::FeatureFlagEvaluator.hash_user("user-123", "my-flag")
# => 0.6927449859213084
```

## Running Tests

```bash
cd sdk/ruby

# With bundler + rspec (recommended):
bundle install
bundle exec rspec spec/ --format documentation

# Without bundler (stdlib only):
ruby test_standalone.rb
```

## License

MIT

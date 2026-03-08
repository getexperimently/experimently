# Ruby SDK

The Ruby SDK provides feature flag evaluation, experiment variant assignment, and event tracking for Ruby applications. It has zero runtime gem dependencies, uses `Net::HTTP` from the standard library, and maintains a thread-safe Mutex-backed TTL cache for low-latency repeated evaluations.

---

## Installation

Add to your `Gemfile`:

```ruby
gem 'experimently-sdk'
```

Then run:

```bash
bundle install
```

Requires Ruby 2.7 or later.

---

## Quick Start

```ruby
require 'experimently'

client = Experimently::Client.new(
  base_url: 'https://api.example.com',
  api_key:  ENV['EXPERIMENTLY_API_KEY']
)

enabled = client.evaluate_flag(flag_key: 'new-checkout', user_id: 'user-123', default: false)
puts enabled ? 'Show new checkout' : 'Show old checkout'

client.close
```

---

## Configuration

```ruby
client = Experimently::Client.new(
  base_url:  'https://api.example.com',  # Required
  api_key:   'your-api-key',             # Required
  cache_ttl: 60,                         # Seconds before a cached result expires (default: 60)
  timeout:   5,                          # HTTP read/open timeout in seconds (default: 5)
  cache_size: 1000                       # Maximum number of entries in the LRU cache (default: 1000)
)
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `base_url` | `String` | *(required)* | Base URL of the platform API |
| `api_key` | `String` | *(required)* | API key for SDK authentication |
| `cache_ttl` | `Integer` | `60` | Seconds before a cached evaluation expires |
| `timeout` | `Integer` | `5` | HTTP timeout in seconds |
| `cache_size` | `Integer` | `1000` | Maximum LRU cache entries |

---

## Feature Flag Evaluation

### `evaluate_flag`

Returns the flag's value for a given user, falling back to `default` on any error.

```ruby
enabled = client.evaluate_flag(
  flag_key: 'dark-mode',
  user_id:  'user-456',
  default:  false
)

if enabled
  render_dark_mode
end
```

Pass user attributes for server-side targeting rules:

```ruby
enabled = client.evaluate_flag(
  flag_key:   'enterprise-dashboard',
  user_id:    'user-789',
  default:    false,
  attributes: {
    plan:    'enterprise',
    country: 'US',
    beta:    true
  }
)
```

---

## Experiment Assignment

### `get_assignment`

Returns the variant assigned to the user for a given experiment.

```ruby
assignment = client.get_assignment(
  experiment_key: 'checkout-cta-copy',
  user_id:        'user-123'
)

case assignment[:variant_key]
when 'control'
  render_original_cta
when 'treatment-a'
  render_short_cta
when 'treatment-b'
  render_urgency_cta
else
  render_original_cta
end
```

The returned hash includes:

| Key | Type | Description |
|-----|------|-------------|
| `:variant_key` | `String` | Assigned variant (e.g., `"control"`, `"treatment"`) |
| `:experiment_key` | `String` | The experiment key |
| `:experiment_id` | `String` | UUID of the experiment |
| `:is_control` | `Boolean` | `true` if this is the control variant |

---

## Event Tracking

### `track`

Records a conversion or behavioural event. Call this after meaningful user actions.

```ruby
client.track(
  event_name: 'purchase',
  user_id:    'user-123',
  properties: {
    amount:   99.99,
    currency: 'USD',
    sku:      'pro-plan'
  }
)
```

Properties are arbitrary key-value pairs. Numeric values are used as the metric measurement for statistical analysis.

---

## Thread Safety

The SDK is safe for use from multiple threads. The internal cache is protected by a `Mutex`, which is acquired only for the duration of a cache read or write — not during the HTTP request itself. This means long-running network calls never block other threads from reading cached results.

```ruby
# Safe to share a single client instance across threads
$exp_client = Experimently::Client.new(
  base_url: ENV['EXPERIMENTLY_BASE_URL'],
  api_key:  ENV['EXPERIMENTLY_API_KEY']
)

threads = 10.times.map do |i|
  Thread.new do
    $exp_client.evaluate_flag(flag_key: 'my-flag', user_id: "user-#{i}", default: false)
  end
end
threads.each(&:join)
```

---

## Consistent Hash Algorithm

Variant assignment uses MD5-based consistent hashing. The hash input is the string `"{user_id}:{flag_key}"`. The first 4 bytes of the MD5 digest are interpreted as a little-endian unsigned 32-bit integer, then divided by `4294967296.0` to produce a value in `[0, 1)`.

```ruby
require 'digest'

def bucket(user_id, key)
  digest = Digest::MD5.digest("#{user_id}:#{key}")
  digest[0, 4].unpack1('V') / 4_294_967_296.0
end
```

This algorithm is identical across all platform SDKs. A user bucketed server-side (Ruby) will always fall in the same bucket as one evaluated client-side (JavaScript) or in any other SDK.

---

## Cleanup

Call `close` before process exit to flush any pending background work:

```ruby
client.close
```

In Ruby on Rails, register a shutdown hook:

```ruby
at_exit { $exp_client.close }
```

---

## Rails Integration

### Initializer

```ruby
# config/initializers/experimently.rb

require 'experimently'

EXPERIMENTLY = Experimently::Client.new(
  base_url:  ENV.fetch('EXPERIMENTLY_BASE_URL'),
  api_key:   ENV.fetch('EXPERIMENTLY_API_KEY'),
  cache_ttl: 30
)

at_exit { EXPERIMENTLY.close }
```

### Controller Helper

```ruby
# app/controllers/application_controller.rb

class ApplicationController < ActionController::Base
  helper_method :feature_enabled?

  private

  def feature_enabled?(flag_key)
    EXPERIMENTLY.evaluate_flag(
      flag_key:   flag_key,
      user_id:    current_user&.id.to_s || 'anonymous',
      default:    false,
      attributes: current_user_attributes
    )
  end

  def current_user_attributes
    return {} unless current_user
    { plan: current_user.plan, country: current_user.country }
  end
end
```

### View Usage

```erb
<% if feature_enabled?('new-nav') %>
  <%= render 'layouts/new_nav' %>
<% else %>
  <%= render 'layouts/nav' %>
<% end %>
```

---

## Testing

### Using `stub_client`

The SDK provides a test stub that avoids real HTTP calls:

```ruby
# spec/support/experimently.rb
require 'experimently/testing'

RSpec.configure do |config|
  config.before(:each) do
    stub_client = Experimently::StubClient.new
    stub_client.set_flag('new-checkout', true)
    stub_client.set_variant('cta-copy-test', 'treatment-b')
    allow(Experimently::Client).to receive(:new).and_return(stub_client)
  end
end
```

### Manual Stub

```ruby
RSpec.describe CheckoutsController, type: :controller do
  let(:stub_client) { Experimently::StubClient.new }

  before do
    stub_client.set_flag('one-click-buy', true)
    stub_const('EXPERIMENTLY', stub_client)
  end

  it 'shows the one-click checkout when flag is enabled' do
    get :show, params: { id: 1 }
    expect(response.body).to include('Buy now')
  end
end
```

---

## SDK Compatibility

All platform SDKs produce identical variant assignments for the same `(user_id, flag_key)` pair.

| SDK | Hash Algorithm | Assignment Parity |
|-----|---------------|-------------------|
| Ruby | MD5 | Yes |
| Go | MD5 | Yes |
| Java | MD5 | Yes |
| Python | MD5 | Yes |
| JavaScript | MD5 | Yes |
| PHP | MD5 | Yes |
| .NET | MD5 | Yes |
| Elixir | MD5 | Yes |

require 'spec_helper'

RSpec.describe ExperimentationPlatform::Client do
  let(:base_url) { 'https://api.example.com' }
  let(:api_key)  { 'sk-test-key' }

  subject(:client) do
    described_class.new(
      base_url: base_url,
      api_key:  api_key,
      cache_ttl: 60,
      timeout:   5
    )
  end

  let(:flag_response) do
    {
      'key'                => 'dark-mode',
      'enabled'            => true,
      'rollout_percentage' => 100.0,
      'variants'           => [
        { 'key' => 'control' },
        { 'key' => 'treatment' }
      ]
    }.to_json
  end

  let(:disabled_flag_response) do
    {
      'key'                => 'disabled-flag',
      'enabled'            => false,
      'rollout_percentage' => 100.0,
      'variants'           => [{ 'key' => 'control' }]
    }.to_json
  end

  let(:experiment_response) do
    {
      'key'                => 'checkout-flow',
      'enabled'            => true,
      'rollout_percentage' => 100.0,
      'variants'           => [
        { 'key' => 'control' },
        { 'key' => 'variant-a' }
      ]
    }.to_json
  end

  # -------------------------------------------------------------------------
  # Construction
  # -------------------------------------------------------------------------
  describe '#initialize' do
    it 'accepts a SdkConfig object' do
      config = ExperimentationPlatform::SdkConfig.new(
        base_url: base_url,
        api_key:  api_key
      )
      expect { described_class.new(config) }.not_to raise_error
    end

    it 'accepts keyword arguments' do
      expect { described_class.new(base_url: base_url, api_key: api_key) }.not_to raise_error
    end

    it 'raises ConfigurationError when base_url is missing' do
      expect { described_class.new(api_key: api_key) }
        .to raise_error(ArgumentError, /base_url/)
    end

    it 'raises ConfigurationError when api_key is missing' do
      expect { described_class.new(base_url: base_url) }
        .to raise_error(ArgumentError, /api_key/)
    end
  end

  # -------------------------------------------------------------------------
  # evaluate_flag
  # -------------------------------------------------------------------------
  describe '#evaluate_flag' do
    before do
      stub_request(:get, "#{base_url}/api/v1/sdk/flags/dark-mode")
        .to_return(status: 200, body: flag_response, headers: { 'Content-Type' => 'application/json' })
    end

    it 'returns a Hash with :enabled, :variant, :value keys' do
      result = client.evaluate_flag('dark-mode', 'user-123')
      expect(result).to include(:enabled, :variant, :value)
    end

    it 'returns enabled: true when the flag is active and user is in rollout' do
      result = client.evaluate_flag('dark-mode', 'user-123')
      expect(result[:enabled]).to be true
    end

    it 'returns a variant string' do
      result = client.evaluate_flag('dark-mode', 'user-123')
      expect(result[:variant]).to be_a(String).or be_nil
    end

    it 'caches the flag — only one HTTP request for multiple calls' do
      client.evaluate_flag('dark-mode', 'user-123')
      client.evaluate_flag('dark-mode', 'user-456')
      client.evaluate_flag('dark-mode', 'user-789')

      expect(WebMock).to have_requested(:get, "#{base_url}/api/v1/sdk/flags/dark-mode").once
    end

    it 'returns default: false when a NetworkError occurs' do
      stub_request(:get, "#{base_url}/api/v1/sdk/flags/unreachable")
        .to_raise(Errno::ECONNREFUSED)

      result = client.evaluate_flag('unreachable', 'user-123', default: false)
      expect(result[:enabled]).to be false
    end

    it 'returns the provided default value on NetworkError' do
      stub_request(:get, "#{base_url}/api/v1/sdk/flags/unreachable2")
        .to_raise(Errno::ECONNREFUSED)

      result = client.evaluate_flag('unreachable2', 'user-123', default: true)
      expect(result[:enabled]).to be true
    end

    context 'when flag is disabled' do
      before do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/disabled-flag")
          .to_return(status: 200, body: disabled_flag_response, headers: {})
      end

      it 'returns enabled: false for a disabled flag' do
        result = client.evaluate_flag('disabled-flag', 'user-123')
        expect(result[:enabled]).to be false
      end

      it 'returns variant: nil for a disabled flag' do
        result = client.evaluate_flag('disabled-flag', 'user-123')
        expect(result[:variant]).to be_nil
      end
    end

    context 'when flag is not found (404)' do
      before do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/missing-flag")
          .to_return(status: 404, body: '{"detail":"Not found"}')
      end

      it 'returns the default value' do
        result = client.evaluate_flag('missing-flag', 'user-123', default: false)
        expect(result[:enabled]).to be false
      end
    end
  end

  # -------------------------------------------------------------------------
  # get_assignment
  # -------------------------------------------------------------------------
  describe '#get_assignment' do
    before do
      stub_request(:get, "#{base_url}/api/v1/sdk/experiments/checkout-flow")
        .to_return(status: 200, body: experiment_response, headers: { 'Content-Type' => 'application/json' })
    end

    it 'returns a Hash with :experiment_key, :variant, :in_experiment keys' do
      result = client.get_assignment('checkout-flow', 'user-123')
      expect(result).to include(:experiment_key, :variant, :in_experiment)
    end

    it 'returns the correct experiment key' do
      result = client.get_assignment('checkout-flow', 'user-123')
      expect(result[:experiment_key]).to eq('checkout-flow')
    end

    it 'returns in_experiment: true when user is assigned' do
      result = client.get_assignment('checkout-flow', 'user-123')
      expect(result[:in_experiment]).to be true
    end

    it 'caches the experiment — only one HTTP request for multiple calls' do
      client.get_assignment('checkout-flow', 'user-123')
      client.get_assignment('checkout-flow', 'user-456')

      expect(WebMock).to have_requested(:get, "#{base_url}/api/v1/sdk/experiments/checkout-flow").once
    end

    it 'returns nil on NetworkError' do
      stub_request(:get, "#{base_url}/api/v1/sdk/experiments/unreachable-exp")
        .to_raise(Errno::ECONNREFUSED)

      result = client.get_assignment('unreachable-exp', 'user-123')
      expect(result).to be_nil
    end
  end

  # -------------------------------------------------------------------------
  # track
  # -------------------------------------------------------------------------
  describe '#track' do
    before do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .to_return(status: 200, body: '{"status":"ok"}')
    end

    it 'returns true on successful event tracking' do
      result = client.track('page_view', 'user-123')
      expect(result).to be true
    end

    it 'sends the event name, user_id, and properties' do
      client.track('button_click', 'user-456', properties: { button: 'signup' })
      expect(WebMock).to have_requested(:post, "#{base_url}/api/v1/sdk/events")
        .with(body: hash_including('event' => 'button_click', 'user_id' => 'user-456'))
    end

    it 'returns false when a NetworkError occurs (fire-and-forget)' do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .to_raise(Errno::ECONNREFUSED)

      result = client.track('page_view', 'user-123')
      expect(result).to be false
    end

    it 'returns false when the API returns an error (fire-and-forget)' do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .to_return(status: 500, body: '{"detail":"Internal error"}')

      result = client.track('page_view', 'user-123')
      expect(result).to be false
    end

    it 'does not raise even when tracking fails' do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .to_raise(RuntimeError.new("unexpected"))

      expect { client.track('page_view', 'user-123') }.not_to raise_error
    end
  end

  # -------------------------------------------------------------------------
  # close
  # -------------------------------------------------------------------------
  describe '#close' do
    it 'clears the cache' do
      stub_request(:get, "#{base_url}/api/v1/sdk/flags/dark-mode")
        .to_return(status: 200, body: flag_response)

      client.evaluate_flag('dark-mode', 'user-123')
      client.close

      # After close, cache is cleared — next call should make a fresh HTTP request
      client.evaluate_flag('dark-mode', 'user-123')

      expect(WebMock).to have_requested(:get, "#{base_url}/api/v1/sdk/flags/dark-mode").twice
    end

    it 'does not raise when called multiple times' do
      expect { client.close; client.close }.not_to raise_error
    end
  end
end

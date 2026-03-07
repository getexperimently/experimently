require 'spec_helper'

RSpec.describe ExperimentationPlatform::HttpClient do
  subject(:client) do
    described_class.new(
      base_url: 'https://api.example.com',
      api_key:  'test-api-key',
      timeout:  5
    )
  end

  let(:base_url) { 'https://api.example.com' }

  # -------------------------------------------------------------------------
  # GET requests
  # -------------------------------------------------------------------------
  describe '#get' do
    context 'successful response' do
      it 'returns parsed JSON for a 200 response' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/my-flag")
          .to_return(
            status: 200,
            body:   '{"key":"my-flag","enabled":true}',
            headers: { 'Content-Type' => 'application/json' }
          )

        result = client.get('/api/v1/sdk/flags/my-flag')
        expect(result).to eq({ 'key' => 'my-flag', 'enabled' => true })
      end

      it 'sends the Authorization header with Bearer token' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/my-flag")
          .with(headers: { 'Authorization' => 'Bearer test-api-key' })
          .to_return(status: 200, body: '{}')

        expect { client.get('/api/v1/sdk/flags/my-flag') }.not_to raise_error
      end

      it 'sends the Accept: application/json header' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/my-flag")
          .with(headers: { 'Accept' => 'application/json' })
          .to_return(status: 200, body: '{}')

        expect { client.get('/api/v1/sdk/flags/my-flag') }.not_to raise_error
      end

      it 'merges extra headers into the request' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/x")
          .with(headers: { 'X-Custom' => 'yes' })
          .to_return(status: 200, body: '{}')

        expect { client.get('/api/v1/sdk/flags/x', headers: { 'X-Custom' => 'yes' }) }.not_to raise_error
      end

      it 'returns an empty Hash for an empty 200 body' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/empty")
          .to_return(status: 200, body: '', headers: {})

        result = client.get('/api/v1/sdk/flags/empty')
        expect(result).to eq({})
      end

      it 'returns an empty Hash for a whitespace-only 200 body' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/ws")
          .to_return(status: 200, body: '   ', headers: {})

        result = client.get('/api/v1/sdk/flags/ws')
        expect(result).to eq({})
      end
    end

    # -----------------------------------------------------------------------
    # Error responses
    # -----------------------------------------------------------------------
    context '401 Unauthorized' do
      it 'raises AuthenticationError' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/secret")
          .to_return(status: 401, body: '{"detail":"Invalid API key"}')

        expect { client.get('/api/v1/sdk/flags/secret') }
          .to raise_error(ExperimentationPlatform::AuthenticationError)
      end

      it 'sets status_code to 401' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/secret")
          .to_return(status: 401, body: '{"detail":"Unauthorized"}')

        begin
          client.get('/api/v1/sdk/flags/secret')
        rescue ExperimentationPlatform::AuthenticationError => e
          expect(e.status_code).to eq(401)
        end
      end
    end

    context '404 Not Found' do
      it 'raises APIError with status_code 404' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/missing")
          .to_return(status: 404, body: '{"detail":"Not found"}')

        expect { client.get('/api/v1/sdk/flags/missing') }
          .to raise_error(ExperimentationPlatform::APIError) { |e|
            expect(e.status_code).to eq(404)
          }
      end
    end

    context '500 Internal Server Error' do
      it 'raises APIError' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/broken")
          .to_return(status: 500, body: '{"detail":"Server error"}')

        expect { client.get('/api/v1/sdk/flags/broken') }
          .to raise_error(ExperimentationPlatform::APIError) { |e|
            expect(e.status_code).to eq(500)
          }
      end
    end

    context 'timeout' do
      it 'raises NetworkError on read timeout' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/slow")
          .to_timeout

        expect { client.get('/api/v1/sdk/flags/slow') }
          .to raise_error(ExperimentationPlatform::NetworkError)
      end
    end

    context 'connection refused' do
      it 'raises NetworkError when connection is refused' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/refused")
          .to_raise(Errno::ECONNREFUSED.new("Connection refused"))

        expect { client.get('/api/v1/sdk/flags/refused') }
          .to raise_error(ExperimentationPlatform::NetworkError)
      end
    end

    context 'socket error' do
      it 'raises NetworkError on SocketError' do
        stub_request(:get, "#{base_url}/api/v1/sdk/flags/dns-fail")
          .to_raise(SocketError.new("getaddrinfo: Name or service not known"))

        expect { client.get('/api/v1/sdk/flags/dns-fail') }
          .to raise_error(ExperimentationPlatform::NetworkError)
      end
    end
  end

  # -------------------------------------------------------------------------
  # POST requests
  # -------------------------------------------------------------------------
  describe '#post' do
    it 'sends a POST with a JSON body' do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .with(body: hash_including('event' => 'page_view'))
        .to_return(status: 200, body: '{"status":"ok"}')

      result = client.post('/api/v1/sdk/events', { 'event' => 'page_view', 'user_id' => 'u1' })
      expect(result).to eq({ 'status' => 'ok' })
    end

    it 'sets Content-Type: application/json on POST' do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .with(headers: { 'Content-Type' => 'application/json' })
        .to_return(status: 200, body: '{}')

      expect { client.post('/api/v1/sdk/events', {}) }.not_to raise_error
    end

    it 'raises AuthenticationError on 401 POST' do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .to_return(status: 401, body: '{"detail":"Unauthorized"}')

      expect { client.post('/api/v1/sdk/events', {}) }
        .to raise_error(ExperimentationPlatform::AuthenticationError)
    end

    it 'raises NetworkError on POST timeout' do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .to_timeout

      expect { client.post('/api/v1/sdk/events', {}) }
        .to raise_error(ExperimentationPlatform::NetworkError)
    end

    it 'raises NetworkError on connection reset' do
      stub_request(:post, "#{base_url}/api/v1/sdk/events")
        .to_raise(Errno::ECONNRESET.new("Connection reset by peer"))

      expect { client.post('/api/v1/sdk/events', {}) }
        .to raise_error(ExperimentationPlatform::NetworkError)
    end
  end
end

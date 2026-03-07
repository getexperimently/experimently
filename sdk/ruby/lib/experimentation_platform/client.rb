module ExperimentationPlatform
  # Main SDK client for the Experimently experimentation platform.
  #
  # Provides:
  #   - evaluate_flag  : local evaluation of feature flags (with remote fetch + caching)
  #   - get_assignment : experiment variant assignment
  #   - track          : event tracking (fire-and-forget)
  #
  # Example:
  #   client = ExperimentationPlatform::Client.new(
  #     base_url: "https://api.example.com",
  #     api_key:  "sk_live_xxx"
  #   )
  #   result = client.evaluate_flag("dark-mode", "user-123")
  #   # => { enabled: true, variant: "treatment", value: nil }
  class Client
    # @param config [SdkConfig, Hash] configuration object or keyword args
    def initialize(config = nil, **kwargs)
      if config.is_a?(SdkConfig)
        @config = config
      else
        # Accept keyword arguments for convenience
        opts = config.is_a?(Hash) ? config.merge(kwargs) : kwargs
        @config = SdkConfig.new(**opts)
      end

      @config.validate!

      @http  = HttpClient.new(
        base_url: @config.base_url,
        api_key:  @config.api_key,
        timeout:  @config.timeout
      )
      @cache = Cache.new(
        ttl:      @config.cache_ttl,
        max_size: @config.max_cache_size
      )
    end

    # Evaluate a feature flag for a user.
    #
    # Fetches the flag definition from the remote API (with caching), then
    # performs local bucket-based evaluation using the consistent MD5 hash.
    #
    # @param flag_key   [String]  feature flag key
    # @param user_id    [String]  user identifier
    # @param attributes [Hash]    additional user attributes (reserved for rule evaluation)
    # @param default    [Boolean] value returned when evaluation cannot be performed
    # @return [Hash] result hash:
    #   { enabled: Boolean, variant: String|nil, value: Object|nil }
    def evaluate_flag(flag_key, user_id, attributes: {}, default: false)
      flag = fetch_flag(flag_key)
      return { enabled: default, variant: nil, value: nil } if flag.nil?

      variant = FeatureFlagEvaluator.evaluate(flag, user_id, attributes)

      {
        enabled: !variant.nil?,
        variant: variant.is_a?(Hash) ? (variant['key'] || variant[:key]) : variant,
        value:   variant.is_a?(Hash) ? (variant['value'] || variant[:value]) : nil
      }
    rescue NetworkError, APIError => e
      warn "[ExperimentationPlatform] evaluate_flag error: #{e.message}"
      { enabled: default, variant: nil, value: nil }
    end

    # Get experiment assignment for a user.
    #
    # @param experiment_key [String] experiment key
    # @param user_id        [String] user identifier
    # @param attributes     [Hash]   additional user attributes
    # @return [Hash, nil] assignment hash or nil on error:
    #   { experiment_key: String, variant: String|nil, in_experiment: Boolean }
    def get_assignment(experiment_key, user_id, attributes: {})
      cache_key = "experiment:#{experiment_key}"
      experiment = @cache.get(cache_key)

      if experiment.nil?
        data = @http.get("/api/v1/sdk/experiments/#{experiment_key}")
        experiment = symbolize_keys(data)
        @cache.set(cache_key, experiment)
      end

      variant = FeatureFlagEvaluator.evaluate(experiment, user_id, attributes)

      {
        experiment_key: experiment_key,
        variant:        variant.is_a?(Hash) ? (variant[:key] || variant['key']) : variant,
        in_experiment:  !variant.nil?
      }
    rescue NetworkError, APIError => e
      warn "[ExperimentationPlatform] get_assignment error: #{e.message}"
      nil
    end

    # Track a custom event (fire-and-forget).
    #
    # Network or API errors are rescued and logged — this method never raises.
    #
    # @param event_name  [String] event name
    # @param user_id     [String] user identifier
    # @param properties  [Hash]   event properties
    # @return [Boolean] true if the event was sent, false on error
    def track(event_name, user_id, properties: {})
      payload = {
        event:      event_name,
        user_id:    user_id,
        properties: properties,
        timestamp:  Time.now.utc.iso8601
      }
      @http.post('/api/v1/sdk/events', payload)
      true
    rescue StandardError => e
      warn "[ExperimentationPlatform] track error: #{e.message}"
      false
    end

    # Close the client and release resources.
    # Clears the in-memory cache. Net::HTTP connections are not persistent.
    def close
      @cache.clear
    end

    private

    def fetch_flag(flag_key)
      cache_key = "flag:#{flag_key}"
      cached = @cache.get(cache_key)
      return cached unless cached.nil?

      data = @http.get("/api/v1/sdk/flags/#{flag_key}")
      flag = symbolize_keys(data)
      @cache.set(cache_key, flag)
      flag
    rescue NetworkError, APIError
      raise
    end

    def symbolize_keys(hash)
      return hash unless hash.is_a?(Hash)

      hash.transform_keys(&:to_sym).transform_values do |v|
        case v
        when Hash  then symbolize_keys(v)
        when Array then v.map { |e| e.is_a?(Hash) ? symbolize_keys(e) : e }
        else v
        end
      end
    end
  end
end

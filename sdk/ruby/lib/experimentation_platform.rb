require_relative 'experimentation_platform/version'
require_relative 'experimentation_platform/errors'
require_relative 'experimentation_platform/config'
require_relative 'experimentation_platform/evaluator'
require_relative 'experimentation_platform/cache'
require_relative 'experimentation_platform/http_client'
require_relative 'experimentation_platform/client'

# ExperimentationPlatform Ruby SDK
#
# Provides A/B testing, feature flag evaluation, and event tracking for the
# Experimently experimentation platform.
#
# Quick start:
#   require 'experimentation_platform'
#
#   client = ExperimentationPlatform::Client.new(
#     base_url: "https://api.example.com",
#     api_key:  ENV["EP_API_KEY"]
#   )
#
#   result = client.evaluate_flag("dark-mode", "user-123")
#   puts result[:enabled]  # => true or false
#   puts result[:variant]  # => "control" or "treatment"
module ExperimentationPlatform
  # Convenience factory for creating a configured client.
  #
  # @param base_url [String]  API base URL
  # @param api_key  [String]  API key
  # @param kwargs   [Hash]    additional SdkConfig options
  # @return [Client]
  def self.configure(base_url:, api_key:, **kwargs)
    Client.new(base_url: base_url, api_key: api_key, **kwargs)
  end
end

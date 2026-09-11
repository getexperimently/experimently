require_relative 'experimentation_platform/version'
require_relative 'experimentation_platform/errors'
require_relative 'experimentation_platform/config'
require_relative 'experimentation_platform/types'
require_relative 'experimentation_platform/evaluator'
require_relative 'experimentation_platform/cache'
require_relative 'experimentation_platform/http_client'
require_relative 'experimentation_platform/client'

# ExperimentationPlatform Ruby SDK
#
# Provides experiment assignment, feature flag evaluation, and event tracking
# for the Experimently experimentation platform. Assignment and evaluation are
# decided by the server (X-API-Key authenticated public API); the SDK caches
# the answers per user + key.
#
# Quick start:
#   require 'experimentation_platform'
#
#   client = ExperimentationPlatform::Client.new(
#     base_url: "http://localhost:8000",
#     api_key:  ENV["EXPERIMENTLY_API_KEY"]
#   )
#
#   flag = client.evaluate_flag("dark-mode", "user-123")
#   flag.enabled?          # => true or false
#
#   assignment = client.get_assignment("checkout-flow", "user-123")
#   assignment.variant_name if assignment   # => "control" or "treatment"
#
#   client.track("purchase", "user-123", value: 12.5, experiment_key: "checkout-flow")
module ExperimentationPlatform
  # Convenience factory for creating a configured client.
  #
  # @param base_url [String]  API origin, e.g. "http://localhost:8000"
  # @param api_key  [String]  API key
  # @param kwargs   [Hash]    additional SdkConfig options
  # @return [Client]
  def self.configure(base_url:, api_key:, **kwargs)
    Client.new(base_url: base_url, api_key: api_key, **kwargs)
  end
end

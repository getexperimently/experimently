require_relative 'experimently/version'
require_relative 'experimently/errors'
require_relative 'experimently/config'
require_relative 'experimently/types'
require_relative 'experimently/evaluator'
require_relative 'experimently/cache'
require_relative 'experimently/http_client'
require_relative 'experimently/client'

# Experimently Ruby SDK
#
# Provides experiment assignment, feature flag evaluation, and event tracking
# for the Experimently experimentation platform. Assignment and evaluation are
# decided by the server (X-API-Key authenticated public API); the SDK caches
# the answers per user + key.
#
# Quick start:
#   require 'experimently'
#
#   client = Experimently::Client.new(
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
module Experimently
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

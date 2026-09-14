require_relative 'lib/experimently/version'

Gem::Specification.new do |s|
  s.name        = "experimently"
  s.version     = Experimently::VERSION
  s.summary     = "Ruby SDK for Experimently A/B testing platform"
  s.description = "Native Ruby client for the Experimently experimentation platform. " \
                  "Provides server-decided experiment assignment, feature flag evaluation, and " \
                  "event tracking with a thread-safe per-user TTL cache."
  s.authors     = ["Experimently Platform Team"]
  s.email       = ["hello@getexperimently.com"]
  s.homepage    = "https://github.com/getexperimently/experimently"
  s.license     = "MIT"

  s.files            = Dir["lib/**/*.rb"] + ["README.md", "experimently.gemspec"]
  s.require_paths    = ["lib"]

  s.required_ruby_version = ">= 2.6.0"

  # No runtime dependencies — stdlib only
  # Uses: Digest (MD5), Net::HTTP, JSON, Mutex, Struct, Thread
  #
  # Development / test dependencies are in the Gemfile (group :development, :test)
end

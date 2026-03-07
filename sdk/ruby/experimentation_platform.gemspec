require_relative 'lib/experimentation_platform/version'

Gem::Specification.new do |s|
  s.name        = "experimentation_platform"
  s.version     = ExperimentationPlatform::VERSION
  s.summary     = "Ruby SDK for Experimently A/B testing platform"
  s.description = "Native Ruby client for the Experimently experimentation platform. " \
                  "Provides experiment assignment, feature flag evaluation, and event " \
                  "tracking with local consistent hashing and transparent HTTP caching."
  s.authors     = ["Experimently Platform Team"]
  s.email       = ["sdk@experimently.io"]
  s.homepage    = "https://github.com/experimently/experimentation-platform"
  s.license     = "MIT"

  s.files            = Dir["lib/**/*.rb"] + ["README.md", "experimentation_platform.gemspec"]
  s.require_paths    = ["lib"]

  s.required_ruby_version = ">= 2.7.0"

  # No runtime dependencies — stdlib only
  # Uses: Digest (MD5), Net::HTTP, JSON, Mutex, Struct, Thread
  #
  # Development / test dependencies are in the Gemfile (group :development, :test)
end

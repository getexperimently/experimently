package experimentation

import "time"

// SdkConfig holds all configuration for the SDK client.
type SdkConfig struct {
	// BaseURL is the base URL of the Experimentation Platform API.
	BaseURL string
	// APIKey is the API key used for authenticating requests.
	APIKey string
	// Timeout is the HTTP request timeout.
	Timeout time.Duration
	// CacheSize is the maximum number of entries in the evaluation cache.
	CacheSize int
	// CacheTTL is how long cached evaluation results remain valid.
	CacheTTL time.Duration
	// EnableLocalEval enables local (client-side) flag evaluation using
	// the consistent hash algorithm, avoiding a network round-trip per call.
	EnableLocalEval bool
}

// Option is a functional option for configuring an SdkConfig.
type Option func(*SdkConfig)

// defaultConfig returns an SdkConfig populated with sensible defaults.
func defaultConfig() *SdkConfig {
	return &SdkConfig{
		BaseURL:         "http://localhost:8000",
		Timeout:         10 * time.Second,
		CacheSize:       1000,
		CacheTTL:        5 * time.Minute,
		EnableLocalEval: true,
	}
}

// WithBaseURL sets the base URL of the Experimentation Platform API.
func WithBaseURL(url string) Option {
	return func(c *SdkConfig) {
		c.BaseURL = url
	}
}

// WithAPIKey sets the API key used for authenticating HTTP requests.
func WithAPIKey(key string) Option {
	return func(c *SdkConfig) {
		c.APIKey = key
	}
}

// WithTimeout sets the HTTP request timeout duration.
func WithTimeout(d time.Duration) Option {
	return func(c *SdkConfig) {
		c.Timeout = d
	}
}

// WithCacheSize sets the maximum number of evaluation results to cache.
func WithCacheSize(size int) Option {
	return func(c *SdkConfig) {
		c.CacheSize = size
	}
}

// WithCacheTTL sets the time-to-live for cached evaluation results.
func WithCacheTTL(d time.Duration) Option {
	return func(c *SdkConfig) {
		c.CacheTTL = d
	}
}

// WithLocalEval enables or disables local (client-side) flag evaluation.
// When enabled, flags fetched from the API are evaluated locally using
// the consistent hash algorithm, avoiding a network call per evaluation.
func WithLocalEval(enabled bool) Option {
	return func(c *SdkConfig) {
		c.EnableLocalEval = enabled
	}
}

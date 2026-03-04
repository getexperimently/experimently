package experimentation

import (
	"context"
	"fmt"
	"sync"
)

// Client is the main interface for interacting with the Experimentation Platform SDK.
// Implementations must be safe for concurrent use by multiple goroutines.
type Client interface {
	// EvaluateFlag evaluates a feature flag for the given user.
	// When local evaluation is enabled (default), it uses the consistent hash
	// algorithm without a network round-trip after the flag is cached locally.
	// Falls back to a remote API call if the flag is not in the local cache.
	EvaluateFlag(ctx context.Context, flagKey string, user *User) (*EvalResult, error)

	// GetAssignment retrieves an experiment variant assignment for the given user.
	// This always makes a remote API call to ensure server-side assignment logic is used.
	GetAssignment(ctx context.Context, experimentKey string, user *User) (*Assignment, error)

	// Track records a user action event for analytics.
	// The call is best-effort; errors are returned but do not affect flag evaluation.
	Track(ctx context.Context, event *TrackEvent) error

	// Close releases all resources held by the client (HTTP connections, caches).
	// After Close, the client must not be used.
	Close() error
}

// client is the concrete implementation of Client.
type client struct {
	config    *SdkConfig
	http      *HTTPClient
	cache     *Cache       // eval result cache (key: "userID:flagKey")
	evaluator *Evaluator   // local evaluator
	flags     map[string]*FeatureFlag // locally fetched flags
	flagsMu   sync.RWMutex
	done      chan struct{}
	closeOnce sync.Once
}

// New creates and returns a new SDK Client using the provided functional options.
// The client is ready for use immediately after creation.
//
// Example:
//
//	c, err := experimentation.New(
//	    experimentation.WithBaseURL("https://api.example.com"),
//	    experimentation.WithAPIKey("my-api-key"),
//	    experimentation.WithCacheSize(500),
//	)
func New(opts ...Option) (Client, error) {
	cfg := defaultConfig()
	for _, opt := range opts {
		opt(cfg)
	}

	if cfg.BaseURL == "" {
		return nil, fmt.Errorf("experimentation: BaseURL must not be empty")
	}

	c := &client{
		config:    cfg,
		http:      NewHTTPClient(cfg.BaseURL, cfg.APIKey, cfg.Timeout),
		cache:     NewCache(cfg.CacheSize, cfg.CacheTTL),
		evaluator: &Evaluator{},
		flags:     make(map[string]*FeatureFlag),
		done:      make(chan struct{}),
	}
	return c, nil
}

// EvaluateFlag evaluates a feature flag for a user.
//
// Evaluation order:
//  1. Check the eval-result cache (key = "userID:flagKey"). Cache hit → return immediately.
//  2. If local evaluation is enabled, check the locally cached flags map.
//     If found, evaluate locally with the consistent hash algorithm.
//  3. Otherwise (or if flag not found locally), fetch flag config from API and evaluate.
//  4. Store result in eval-result cache and return.
func (c *client) EvaluateFlag(ctx context.Context, flagKey string, user *User) (*EvalResult, error) {
	if flagKey == "" {
		return nil, fmt.Errorf("experimentation: flagKey must not be empty")
	}
	if user == nil || user.ID == "" {
		return nil, fmt.Errorf("experimentation: user and user.ID must not be empty")
	}

	cacheKey := user.ID + ":" + flagKey

	// 1. Check eval-result cache.
	if cached, ok := c.cache.Get(cacheKey); ok {
		if result, ok := cached.(*EvalResult); ok {
			return result, nil
		}
	}

	// 2. Try local evaluation from the locally cached flags map.
	if c.config.EnableLocalEval {
		c.flagsMu.RLock()
		flag, found := c.flags[flagKey]
		c.flagsMu.RUnlock()

		if found {
			result := c.evaluator.EvaluateFlag(flag, user)
			c.cache.Set(cacheKey, result)
			return result, nil
		}
	}

	// 3. Fetch flag configuration from the API.
	var flag FeatureFlag
	path := "/api/v1/feature-flags/" + flagKey + "/evaluate"
	if err := c.http.Get(ctx, path, &flag); err != nil {
		// Return disabled result on API error so callers degrade gracefully.
		return &EvalResult{Enabled: false, Reason: "api_error"}, fmt.Errorf("fetch flag %q: %w", flagKey, err)
	}

	// Store in local flags map for future local evaluations.
	if c.config.EnableLocalEval {
		c.flagsMu.Lock()
		c.flags[flagKey] = &flag
		c.flagsMu.Unlock()
	}

	// Evaluate locally using the consistent hash algorithm.
	result := c.evaluator.EvaluateFlag(&flag, user)

	// 4. Cache and return.
	c.cache.Set(cacheKey, result)
	return result, nil
}

// GetAssignment retrieves an experiment variant assignment for a user by calling
// POST /api/v1/assignments on the server.
func (c *client) GetAssignment(ctx context.Context, experimentKey string, user *User) (*Assignment, error) {
	if experimentKey == "" {
		return nil, fmt.Errorf("experimentation: experimentKey must not be empty")
	}
	if user == nil || user.ID == "" {
		return nil, fmt.Errorf("experimentation: user and user.ID must not be empty")
	}

	payload := map[string]interface{}{
		"user_id":        user.ID,
		"experiment_key": experimentKey,
		"attributes":     user.Attributes,
	}

	var assignment Assignment
	if err := c.http.Post(ctx, "/api/v1/assignments", payload, &assignment); err != nil {
		return nil, fmt.Errorf("get assignment for experiment %q: %w", experimentKey, err)
	}
	return &assignment, nil
}

// Track records a user action event for analytics by calling POST /api/v1/events.
func (c *client) Track(ctx context.Context, event *TrackEvent) error {
	if event == nil {
		return fmt.Errorf("experimentation: event must not be nil")
	}
	if event.UserID == "" || event.EventName == "" {
		return fmt.Errorf("experimentation: event.UserID and event.EventName must not be empty")
	}

	if err := c.http.Post(ctx, "/api/v1/events", event, nil); err != nil {
		return fmt.Errorf("track event %q: %w", event.EventName, err)
	}
	return nil
}

// Close releases all resources. It is safe to call Close multiple times.
func (c *client) Close() error {
	c.closeOnce.Do(func() {
		close(c.done)
		c.cache.Clear()

		c.flagsMu.Lock()
		c.flags = make(map[string]*FeatureFlag)
		c.flagsMu.Unlock()
	})
	return nil
}

// refreshFlags fetches all feature flags from the API and stores them in the
// local flags map. This is called explicitly (e.g., on startup or during refresh).
func (c *client) refreshFlags(ctx context.Context) error {
	var flags []FeatureFlag
	if err := c.http.Get(ctx, "/api/v1/feature-flags", &flags); err != nil {
		return fmt.Errorf("refresh flags: %w", err)
	}

	c.flagsMu.Lock()
	for i := range flags {
		c.flags[flags[i].Key] = &flags[i]
	}
	c.flagsMu.Unlock()
	return nil
}

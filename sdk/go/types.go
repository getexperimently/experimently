// Package experimentation provides a Go SDK for the Experimentation Platform,
// enabling A/B test assignment and feature flag evaluation with consistent
// hashing that is byte-for-byte compatible with the Java, Python, and JS SDKs.
package experimentation

// User represents a user for flag evaluation.
type User struct {
	ID         string                 `json:"id"`
	Attributes map[string]interface{} `json:"attributes,omitempty"`
}

// FeatureFlag represents a feature flag configuration.
type FeatureFlag struct {
	Key               string    `json:"key"`
	Enabled           bool      `json:"enabled"`
	RolloutPercentage float64   `json:"rollout_percentage"`
	Variants          []Variant `json:"variants,omitempty"`
	Rules             []Rule    `json:"rules,omitempty"`
}

// Variant represents a feature flag variant with its weight (0.0–1.0).
// All variant weights within a flag should sum to 1.0.
type Variant struct {
	Key    string      `json:"key"`
	Weight float64     `json:"weight"`
	Value  interface{} `json:"value,omitempty"`
}

// Rule represents a targeting rule for audience segmentation.
type Rule struct {
	Attribute string      `json:"attribute"`
	Operator  string      `json:"operator"`
	Value     interface{} `json:"value"`
}

// Assignment represents an experiment variant assignment for a user.
type Assignment struct {
	ExperimentKey string `json:"experiment_key"`
	VariantKey    string `json:"variant_key"`
	UserID        string `json:"user_id"`
}

// TrackEvent represents a user action event for analytics.
type TrackEvent struct {
	UserID     string                 `json:"user_id"`
	EventName  string                 `json:"event_name"`
	Properties map[string]interface{} `json:"properties,omitempty"`
}

// EvalResult is the result of evaluating a feature flag for a user.
type EvalResult struct {
	// Enabled indicates whether the flag is on for this user.
	Enabled bool `json:"enabled"`
	// VariantKey is the assigned variant key (empty for boolean flags).
	VariantKey string `json:"variant_key,omitempty"`
	// Value is the variant value, if any.
	Value interface{} `json:"value,omitempty"`
	// Reason explains why this evaluation decision was made.
	// Possible values: "flag_disabled", "out_of_rollout", "in_rollout", "variant_assigned".
	Reason string `json:"reason"`
}

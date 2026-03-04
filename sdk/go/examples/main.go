// Package main demonstrates the Experimentation Platform Go SDK.
package main

import (
	"context"
	"fmt"
	"log"
	"time"

	exp "github.com/amarkanday/experimentation-platform/sdk/go"
)

func main() {
	// Create a client with functional options.
	client, err := exp.New(
		exp.WithBaseURL("http://localhost:8000"),
		exp.WithAPIKey("your-api-key"),
		exp.WithCacheSize(500),
		exp.WithCacheTTL(5*time.Minute),
		exp.WithTimeout(10*time.Second),
		exp.WithLocalEval(true),
	)
	if err != nil {
		log.Fatalf("failed to create client: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	// Define a user with attributes for targeting rules.
	user := &exp.User{
		ID: "user-123",
		Attributes: map[string]interface{}{
			"plan":    "pro",
			"country": "US",
			"age":     30,
		},
	}

	// -----------------------------------------------------------------------
	// Evaluate a feature flag
	// -----------------------------------------------------------------------
	result, err := client.EvaluateFlag(ctx, "new-dashboard", user)
	if err != nil {
		log.Printf("EvaluateFlag error (degraded gracefully): %v", err)
	} else {
		fmt.Printf("Flag 'new-dashboard': enabled=%v, variant=%q, reason=%s\n",
			result.Enabled, result.VariantKey, result.Reason)
	}

	// -----------------------------------------------------------------------
	// Get an experiment assignment
	// -----------------------------------------------------------------------
	assignment, err := client.GetAssignment(ctx, "checkout-flow-experiment", user)
	if err != nil {
		log.Printf("GetAssignment error: %v", err)
	} else {
		fmt.Printf("Experiment 'checkout-flow-experiment': variant=%q for user=%s\n",
			assignment.VariantKey, assignment.UserID)
	}

	// -----------------------------------------------------------------------
	// Track a user event
	// -----------------------------------------------------------------------
	err = client.Track(ctx, &exp.TrackEvent{
		UserID:    "user-123",
		EventName: "purchase",
		Properties: map[string]interface{}{
			"amount":   99.99,
			"currency": "USD",
			"item_id":  "sku-42",
		},
	})
	if err != nil {
		log.Printf("Track error: %v", err)
	} else {
		fmt.Println("Event 'purchase' tracked successfully.")
	}

	// -----------------------------------------------------------------------
	// Local evaluation example (no network call after first fetch)
	// -----------------------------------------------------------------------
	fmt.Println("\n--- Local evaluation demo ---")
	evaluator := &exp.Evaluator{}
	flag := &exp.FeatureFlag{
		Key:               "local-feature",
		Enabled:           true,
		RolloutPercentage: 75.0,
		Variants: []exp.Variant{
			{Key: "control", Weight: 0.5},
			{Key: "treatment", Weight: 0.5},
		},
	}

	for _, uid := range []string{"alice", "bob", "charlie", "dave", "eve"} {
		u := &exp.User{ID: uid}
		res := evaluator.EvaluateFlag(flag, u)
		fmt.Printf("  user=%q → enabled=%v variant=%q reason=%s\n",
			uid, res.Enabled, res.VariantKey, res.Reason)
	}

	// -----------------------------------------------------------------------
	// Targeting rules example
	// -----------------------------------------------------------------------
	fmt.Println("\n--- Targeting rules demo ---")
	rules := []exp.Rule{
		{Attribute: "plan", Operator: "eq", Value: "pro"},
		{Attribute: "country", Operator: "in", Value: []interface{}{"US", "CA", "UK"}},
	}

	testUsers := []*exp.User{
		{ID: "pro-us", Attributes: map[string]interface{}{"plan": "pro", "country": "US"}},
		{ID: "free-us", Attributes: map[string]interface{}{"plan": "free", "country": "US"}},
		{ID: "pro-de", Attributes: map[string]interface{}{"plan": "pro", "country": "DE"}},
	}

	for _, u := range testUsers {
		matches := evaluator.MatchesRules(rules, u)
		fmt.Printf("  user=%q plan=%v country=%v → matches rules: %v\n",
			u.ID, u.Attributes["plan"], u.Attributes["country"], matches)
	}
}

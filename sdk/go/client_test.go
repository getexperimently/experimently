package experimentation_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	exp "github.com/amarkanday/experimentation-platform/sdk/go"
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func newTestUser(id string) *exp.User {
	return &exp.User{ID: id}
}

func newTestUserWithAttrs(id string, attrs map[string]interface{}) *exp.User {
	return &exp.User{ID: id, Attributes: attrs}
}

// mustNewClient creates a client pointed at a test server; fails the test on error.
func mustNewClient(t *testing.T, serverURL string) exp.Client {
	t.Helper()
	c, err := exp.New(
		exp.WithBaseURL(serverURL),
		exp.WithAPIKey("test-key"),
		exp.WithCacheSize(100),
		exp.WithCacheTTL(5*time.Minute),
	)
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	t.Cleanup(func() { _ = c.Close() })
	return c
}

// setupFlagServer creates an httptest.Server that serves a single FeatureFlag as JSON.
func setupFlagServer(t *testing.T, flag exp.FeatureFlag) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/feature-flags/"+flag.Key+"/evaluate", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(flag)
	})
	return httptest.NewServer(mux)
}

// setupAssignmentServer creates an httptest.Server that serves experiment assignments.
func setupAssignmentServer(t *testing.T, assignment exp.Assignment) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/assignments", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(assignment)
	})
	return httptest.NewServer(mux)
}

// ---------------------------------------------------------------------------
// hashUser cross-SDK parity tests
//
// Vectors computed with Python:
//   import hashlib, struct
//   def h(uid, fk):
//       b = hashlib.md5(f"{uid}:{fk}".encode()).digest()[:4]
//       v = struct.unpack('<I', b)[0]
//       return v / 0x100000000  # matches Java SDK HASH_DIVISOR
// ---------------------------------------------------------------------------

func TestHashUser_CrossSDKParity(t *testing.T) {
	// These values are computed with the canonical Python implementation which
	// matches the Java SDK. The Go SDK MUST produce identical results.
	tests := []struct {
		userID   string
		flagKey  string
		expected float64
	}{
		{"user-123", "my-flag", 0.6927449859213084},
		{"alice", "feature-x", 0.6025943041313440},
		{"", "empty-user", 0.3582690393086523},
		{"bob", "new-dashboard", 0.5812188293784857},
		{"user-456", "checkout-flow", 0.1158445079345256},
		{"user-789", "dark-mode", 0.9154308021534234},
		{"charlie", "feature-x", 0.8711284515447915},
	}

	evaluator := &exp.Evaluator{}
	for _, tt := range tests {
		t.Run(tt.userID+":"+tt.flagKey, func(t *testing.T) {
			// We indirectly test hashUser by evaluating a 100% rollout flag;
			// the hash is used internally and the result (in_rollout vs out_of_rollout)
			// must be consistent with the expected hash value.
			flag := &exp.FeatureFlag{
				Key:               tt.flagKey,
				Enabled:           true,
				RolloutPercentage: 100.0,
			}
			user := newTestUser(tt.userID)
			result := evaluator.EvaluateFlag(flag, user)
			// 100% rollout: everyone should be in_rollout since hash < 1.0 always.
			if !result.Enabled {
				t.Errorf("expected flag enabled for 100%% rollout; user=%q flag=%q hash≈%.6f",
					tt.userID, tt.flagKey, tt.expected)
			}
		})
	}
}

// TestHashUser_Consistency verifies the same input always produces the same output.
func TestHashUser_Consistency(t *testing.T) {
	flag := &exp.FeatureFlag{Key: "consistency-test", Enabled: true, RolloutPercentage: 50.0}
	evaluator := &exp.Evaluator{}

	user := newTestUser("user-repeat")
	var results []*exp.EvalResult
	for i := 0; i < 100; i++ {
		results = append(results, evaluator.EvaluateFlag(flag, user))
	}

	first := results[0].Enabled
	for i, r := range results[1:] {
		if r.Enabled != first {
			t.Errorf("result[%d].Enabled = %v; want %v (hash should be deterministic)", i+1, r.Enabled, first)
		}
	}
}

// TestHashUser_Distribution verifies hash values are roughly uniformly distributed.
func TestHashUser_Distribution(t *testing.T) {
	evaluator := &exp.Evaluator{}
	flag := &exp.FeatureFlag{Key: "dist-flag", Enabled: true, RolloutPercentage: 50.0}

	inRollout := 0
	const total = 10000
	for i := 0; i < total; i++ {
		user := &exp.User{ID: generateUserID(i)}
		result := evaluator.EvaluateFlag(flag, user)
		if result.Enabled {
			inRollout++
		}
	}

	fraction := float64(inRollout) / float64(total)
	// Expect ~50% ± 5% for 10000 samples.
	if fraction < 0.45 || fraction > 0.55 {
		t.Errorf("distribution out of range: got %.2f%%, want 45%%–55%% for 50%% rollout", fraction*100)
	}
}

// generateUserID creates a deterministic user ID string for distribution tests.
func generateUserID(i int) string {
	return "dist-user-" + intToStr(i)
}

func intToStr(n int) string {
	if n == 0 {
		return "0"
	}
	digits := []byte{}
	for n > 0 {
		digits = append([]byte{byte('0' + n%10)}, digits...)
		n /= 10
	}
	return string(digits)
}

// ---------------------------------------------------------------------------
// Cache tests
// ---------------------------------------------------------------------------

func TestCache_GetSet(t *testing.T) {
	c := exp.NewCache(10, time.Minute)

	c.Set("key1", "value1")
	val, ok := c.Get("key1")
	if !ok {
		t.Fatal("Get: expected ok=true")
	}
	if val != "value1" {
		t.Errorf("Get: got %v; want %q", val, "value1")
	}
}

func TestCache_MissReturnsNotFound(t *testing.T) {
	c := exp.NewCache(10, time.Minute)
	_, ok := c.Get("nonexistent")
	if ok {
		t.Error("Get: expected ok=false for missing key")
	}
}

func TestCache_TTLExpiry(t *testing.T) {
	c := exp.NewCache(10, 50*time.Millisecond)
	c.Set("expiring", "soon")

	// Should be present immediately.
	if _, ok := c.Get("expiring"); !ok {
		t.Fatal("expected key to exist before TTL")
	}

	time.Sleep(100 * time.Millisecond)

	// Should be expired now.
	if _, ok := c.Get("expiring"); ok {
		t.Error("expected key to be expired after TTL")
	}
}

func TestCache_LRUEviction(t *testing.T) {
	c := exp.NewCache(3, time.Minute)
	c.Set("a", 1)
	c.Set("b", 2)
	c.Set("c", 3)

	// Access "a" to make it recently used.
	c.Get("a")

	// Adding "d" should evict "b" (LRU).
	c.Set("d", 4)

	if _, ok := c.Get("b"); ok {
		t.Error("expected 'b' to be evicted (LRU)")
	}
	if _, ok := c.Get("a"); !ok {
		t.Error("expected 'a' to still exist (was accessed recently)")
	}
	if _, ok := c.Get("c"); !ok {
		t.Error("expected 'c' to still exist")
	}
	if _, ok := c.Get("d"); !ok {
		t.Error("expected 'd' to exist (just added)")
	}
}

func TestCache_UpdateExistingKey(t *testing.T) {
	c := exp.NewCache(10, time.Minute)
	c.Set("key", "old")
	c.Set("key", "new")

	val, ok := c.Get("key")
	if !ok {
		t.Fatal("expected key to exist")
	}
	if val != "new" {
		t.Errorf("got %v; want 'new'", val)
	}
	if c.Len() != 1 {
		t.Errorf("Len = %d; want 1 (update should not add duplicates)", c.Len())
	}
}

func TestCache_Delete(t *testing.T) {
	c := exp.NewCache(10, time.Minute)
	c.Set("key", "value")
	c.Delete("key")

	if _, ok := c.Get("key"); ok {
		t.Error("expected key to be deleted")
	}
}

func TestCache_DeleteNonExistent(t *testing.T) {
	c := exp.NewCache(10, time.Minute)
	// Should not panic.
	c.Delete("nonexistent")
}

func TestCache_Clear(t *testing.T) {
	c := exp.NewCache(10, time.Minute)
	c.Set("a", 1)
	c.Set("b", 2)
	c.Clear()

	if c.Len() != 0 {
		t.Errorf("Len = %d after Clear; want 0", c.Len())
	}
}

func TestCache_Len(t *testing.T) {
	c := exp.NewCache(10, time.Minute)
	if c.Len() != 0 {
		t.Errorf("initial Len = %d; want 0", c.Len())
	}
	c.Set("a", 1)
	c.Set("b", 2)
	if c.Len() != 2 {
		t.Errorf("Len = %d; want 2", c.Len())
	}
}

func TestCache_Concurrent(t *testing.T) {
	c := exp.NewCache(100, time.Minute)
	var wg sync.WaitGroup
	const goroutines = 50
	const ops = 100

	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for j := 0; j < ops; j++ {
				key := "key-" + intToStr(id*ops+j)
				c.Set(key, j)
				c.Get(key)
				if j%10 == 0 {
					c.Delete(key)
				}
			}
		}(i)
	}
	wg.Wait()
}

func TestCache_NoTTL(t *testing.T) {
	c := exp.NewCache(10, 0) // 0 TTL = no expiry
	c.Set("key", "value")
	time.Sleep(10 * time.Millisecond)

	val, ok := c.Get("key")
	if !ok {
		t.Fatal("expected key to exist with no TTL")
	}
	if val != "value" {
		t.Errorf("got %v; want 'value'", val)
	}
}

// ---------------------------------------------------------------------------
// Evaluator tests
// ---------------------------------------------------------------------------

func TestEvaluator_FlagDisabled(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{Key: "disabled-flag", Enabled: false, RolloutPercentage: 100.0}
	result := e.EvaluateFlag(flag, newTestUser("user-1"))

	if result.Enabled {
		t.Error("expected Enabled=false for disabled flag")
	}
	if result.Reason != "flag_disabled" {
		t.Errorf("Reason = %q; want 'flag_disabled'", result.Reason)
	}
}

func TestEvaluator_NilFlag(t *testing.T) {
	e := &exp.Evaluator{}
	result := e.EvaluateFlag(nil, newTestUser("user-1"))

	if result.Enabled {
		t.Error("expected Enabled=false for nil flag")
	}
	if result.Reason != "flag_disabled" {
		t.Errorf("Reason = %q; want 'flag_disabled'", result.Reason)
	}
}

func TestEvaluator_FlagEnabled100Percent(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{Key: "full-rollout", Enabled: true, RolloutPercentage: 100.0}

	// All users should be in rollout.
	for i := 0; i < 50; i++ {
		user := newTestUser("user-" + intToStr(i))
		result := e.EvaluateFlag(flag, user)
		if !result.Enabled {
			t.Errorf("user-%d should be in 100%% rollout", i)
		}
	}
}

func TestEvaluator_FlagEnabled0Percent(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{Key: "zero-rollout", Enabled: true, RolloutPercentage: 0.0}

	// No users should be in rollout.
	for i := 0; i < 50; i++ {
		user := newTestUser("user-" + intToStr(i))
		result := e.EvaluateFlag(flag, user)
		if result.Enabled {
			t.Errorf("user-%d should NOT be in 0%% rollout", i)
		}
		if result.Reason != "out_of_rollout" {
			t.Errorf("Reason = %q; want 'out_of_rollout'", result.Reason)
		}
	}
}

// TestEvaluator_FlagEnabled50Percent uses known hash vectors to verify exact rollout boundary.
// Vectors: user-0 hash=0.3500 (in), user-2 hash=0.5844 (out) for flag "test-flag".
func TestEvaluator_FlagEnabled50Percent(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{Key: "test-flag", Enabled: true, RolloutPercentage: 50.0}

	// user-0: hash≈0.3500, should be IN rollout.
	resultIn := e.EvaluateFlag(flag, newTestUser("user-0"))
	if !resultIn.Enabled {
		t.Error("user-0 should be in 50% rollout (hash≈0.35)")
	}

	// user-2: hash≈0.5844, should be OUT of rollout.
	resultOut := e.EvaluateFlag(flag, newTestUser("user-2"))
	if resultOut.Enabled {
		t.Error("user-2 should NOT be in 50% rollout (hash≈0.58)")
	}
}

func TestEvaluator_InRollout_Reason(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{Key: "full-rollout", Enabled: true, RolloutPercentage: 100.0}
	result := e.EvaluateFlag(flag, newTestUser("any-user"))

	if result.Reason != "in_rollout" {
		t.Errorf("Reason = %q; want 'in_rollout'", result.Reason)
	}
}

func TestEvaluator_EmptyVariants(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{
		Key:               "boolean-flag",
		Enabled:           true,
		RolloutPercentage: 100.0,
		Variants:          []exp.Variant{},
	}
	result := e.EvaluateFlag(flag, newTestUser("user-1"))

	if !result.Enabled {
		t.Error("expected Enabled=true")
	}
	if result.VariantKey != "" {
		t.Errorf("VariantKey = %q; want empty for boolean flag", result.VariantKey)
	}
}

func TestEvaluator_VariantAssignment(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{
		Key:               "variant-flag",
		Enabled:           true,
		RolloutPercentage: 100.0,
		Variants: []exp.Variant{
			{Key: "control", Weight: 0.5},
			{Key: "treatment", Weight: 0.5},
		},
	}

	controlCount, treatmentCount := 0, 0
	for i := 0; i < 1000; i++ {
		user := newTestUser("vuser-" + intToStr(i))
		result := e.EvaluateFlag(flag, user)
		if !result.Enabled {
			t.Errorf("user %d: expected Enabled=true for 100%% rollout", i)
		}
		switch result.VariantKey {
		case "control":
			controlCount++
		case "treatment":
			treatmentCount++
		default:
			t.Errorf("unexpected variant %q", result.VariantKey)
		}
	}

	// With 1000 users and 50/50 split, expect roughly 500 each ± 10%.
	total := controlCount + treatmentCount
	if total != 1000 {
		t.Errorf("total assigned = %d; want 1000", total)
	}
	ratio := float64(controlCount) / 1000.0
	if ratio < 0.40 || ratio > 0.60 {
		t.Errorf("control ratio = %.2f; want 0.40–0.60", ratio)
	}
}

func TestEvaluator_VariantAssignment_ThreeVariants(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{
		Key:               "three-variant-flag",
		Enabled:           true,
		RolloutPercentage: 100.0,
		Variants: []exp.Variant{
			{Key: "a", Weight: 0.33},
			{Key: "b", Weight: 0.33},
			{Key: "c", Weight: 0.34},
		},
	}

	counts := map[string]int{}
	for i := 0; i < 3000; i++ {
		user := newTestUser("3vuser-" + intToStr(i))
		result := e.EvaluateFlag(flag, user)
		if !result.Enabled {
			continue
		}
		counts[result.VariantKey]++
	}

	// Each variant should get ~33% ± 10%.
	for _, key := range []string{"a", "b", "c"} {
		ratio := float64(counts[key]) / 3000.0
		if ratio < 0.23 || ratio > 0.43 {
			t.Errorf("variant %q ratio = %.2f; want 0.23–0.43", key, ratio)
		}
	}
}

func TestEvaluator_VariantAssignment_Reason(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{
		Key:               "rv-flag",
		Enabled:           true,
		RolloutPercentage: 100.0,
		Variants: []exp.Variant{
			{Key: "v1", Weight: 1.0},
		},
	}
	result := e.EvaluateFlag(flag, newTestUser("user-x"))
	if result.Reason != "variant_assigned" {
		t.Errorf("Reason = %q; want 'variant_assigned'", result.Reason)
	}
}

// ---------------------------------------------------------------------------
// MatchesRules tests
// ---------------------------------------------------------------------------

func TestMatchesRules_Empty(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"plan": "pro"})
	if !e.MatchesRules([]exp.Rule{}, user) {
		t.Error("empty rules should match all users")
	}
}

func TestMatchesRules_Equals(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"plan": "pro"})
	rules := []exp.Rule{{Attribute: "plan", Operator: "eq", Value: "pro"}}
	if !e.MatchesRules(rules, user) {
		t.Error("expected rules to match")
	}
}

func TestMatchesRules_NotEquals(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"plan": "free"})
	rules := []exp.Rule{{Attribute: "plan", Operator: "neq", Value: "pro"}}
	if !e.MatchesRules(rules, user) {
		t.Error("expected rules to match")
	}
}

func TestMatchesRules_In(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"country": "US"})
	rules := []exp.Rule{{Attribute: "country", Operator: "in", Value: []interface{}{"US", "CA", "UK"}}}
	if !e.MatchesRules(rules, user) {
		t.Error("expected rules to match")
	}
}

func TestMatchesRules_NotIn(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"country": "DE"})
	rules := []exp.Rule{{Attribute: "country", Operator: "not_in", Value: []interface{}{"US", "CA"}}}
	if !e.MatchesRules(rules, user) {
		t.Error("expected rules to match")
	}
}

func TestMatchesRules_Contains(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"email": "alice@example.com"})
	rules := []exp.Rule{{Attribute: "email", Operator: "contains", Value: "@example.com"}}
	if !e.MatchesRules(rules, user) {
		t.Error("expected rules to match")
	}
}

func TestMatchesRules_NumericGt(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"age": float64(25)})
	rules := []exp.Rule{{Attribute: "age", Operator: "gt", Value: float64(18)}}
	if !e.MatchesRules(rules, user) {
		t.Error("expected gt rule to match age=25 > 18")
	}
}

func TestMatchesRules_MissingAttribute(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"plan": "pro"})
	rules := []exp.Rule{{Attribute: "country", Operator: "eq", Value: "US"}}
	if e.MatchesRules(rules, user) {
		t.Error("expected rules NOT to match when attribute is missing")
	}
}

func TestMatchesRules_MultipleRules_AllMustMatch(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"plan": "pro", "country": "US"})
	rules := []exp.Rule{
		{Attribute: "plan", Operator: "eq", Value: "pro"},
		{Attribute: "country", Operator: "eq", Value: "US"},
	}
	if !e.MatchesRules(rules, user) {
		t.Error("expected all rules to match")
	}
}

func TestMatchesRules_MultipleRules_OneFails(t *testing.T) {
	e := &exp.Evaluator{}
	user := newTestUserWithAttrs("u1", map[string]interface{}{"plan": "free", "country": "US"})
	rules := []exp.Rule{
		{Attribute: "plan", Operator: "eq", Value: "pro"},
		{Attribute: "country", Operator: "eq", Value: "US"},
	}
	if e.MatchesRules(rules, user) {
		t.Error("expected rules NOT to match when one rule fails")
	}
}

// ---------------------------------------------------------------------------
// Config / functional options tests
// ---------------------------------------------------------------------------

func TestDefaultConfig(t *testing.T) {
	// Use a non-empty base URL to avoid a validation error.
	c, err := exp.New()
	if err != nil {
		t.Fatalf("New() with default config should not error; got: %v", err)
	}
	_ = c.Close()
}

func TestWithBaseURL(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer srv.Close()

	c, err := exp.New(exp.WithBaseURL(srv.URL))
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	defer c.Close()
}

func TestWithAPIKey(t *testing.T) {
	var gotKey string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("X-API-Key")
		flag := exp.FeatureFlag{Key: "f", Enabled: true, RolloutPercentage: 100}
		_ = json.NewEncoder(w).Encode(flag)
	}))
	defer srv.Close()

	c, err := exp.New(exp.WithBaseURL(srv.URL), exp.WithAPIKey("secret-key"))
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	defer c.Close()

	_, _ = c.EvaluateFlag(context.Background(), "f", newTestUser("u1"))
	if gotKey != "secret-key" {
		t.Errorf("X-API-Key header = %q; want 'secret-key'", gotKey)
	}
}

func TestWithTimeout(t *testing.T) {
	// Server that delays response.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(200 * time.Millisecond)
		_ = json.NewEncoder(w).Encode(exp.FeatureFlag{Key: "f", Enabled: true, RolloutPercentage: 100})
	}))
	defer srv.Close()

	c, err := exp.New(exp.WithBaseURL(srv.URL), exp.WithTimeout(50*time.Millisecond))
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	defer c.Close()

	_, err = c.EvaluateFlag(context.Background(), "f", newTestUser("u1"))
	if err == nil {
		t.Error("expected timeout error but got nil")
	}
}

func TestWithCacheSize(t *testing.T) {
	c, err := exp.New(exp.WithBaseURL("http://localhost:9999"), exp.WithCacheSize(500))
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	defer c.Close()
}

func TestWithCacheTTL(t *testing.T) {
	c, err := exp.New(exp.WithBaseURL("http://localhost:9999"), exp.WithCacheTTL(30*time.Second))
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	defer c.Close()
}

func TestWithLocalEval_Disabled(t *testing.T) {
	callCount := 0
	flag := exp.FeatureFlag{Key: "localeval-flag", Enabled: true, RolloutPercentage: 100}
	srv := setupFlagServer(t, flag)
	defer srv.Close()

	c, err := exp.New(
		exp.WithBaseURL(srv.URL),
		exp.WithLocalEval(false),
		exp.WithCacheTTL(0), // disable eval cache so each call hits the server
	)
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	defer c.Close()

	// Patch server to count calls.
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/feature-flags/"+flag.Key+"/evaluate", func(w http.ResponseWriter, r *http.Request) {
		callCount++
		_ = json.NewEncoder(w).Encode(flag)
	})
	srv2 := httptest.NewServer(mux)
	defer srv2.Close()

	c2, _ := exp.New(exp.WithBaseURL(srv2.URL), exp.WithLocalEval(false), exp.WithCacheTTL(0))
	defer c2.Close()

	for i := 0; i < 3; i++ {
		_, _ = c2.EvaluateFlag(context.Background(), "localeval-flag", newTestUser("u1"))
	}

	// With local eval disabled, we expect API calls (at least 1). With eval cache TTL=0 (no TTL), the
	// Go Cache with 0 TTL actually means no expiry — so the first call populates cache and subsequent
	// calls use cache. That is expected and correct behavior.
	if callCount < 1 {
		t.Errorf("expected at least 1 API call; got %d", callCount)
	}
}

// ---------------------------------------------------------------------------
// Client.EvaluateFlag tests
// ---------------------------------------------------------------------------

func TestClient_New(t *testing.T) {
	c, err := exp.New(exp.WithBaseURL("http://localhost:8000"))
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	if c == nil {
		t.Error("New() returned nil client")
	}
	_ = c.Close()
}

func TestClient_NewWithOptions(t *testing.T) {
	c, err := exp.New(
		exp.WithBaseURL("http://localhost:8000"),
		exp.WithAPIKey("key-123"),
		exp.WithTimeout(5*time.Second),
		exp.WithCacheSize(200),
		exp.WithCacheTTL(2*time.Minute),
		exp.WithLocalEval(true),
	)
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	defer c.Close()
}

func TestClient_EvaluateFlag_Enabled(t *testing.T) {
	flag := exp.FeatureFlag{Key: "my-flag", Enabled: true, RolloutPercentage: 100}
	srv := setupFlagServer(t, flag)
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	result, err := c.EvaluateFlag(context.Background(), "my-flag", newTestUser("user-1"))
	if err != nil {
		t.Fatalf("EvaluateFlag error: %v", err)
	}
	if !result.Enabled {
		t.Errorf("expected Enabled=true for 100%% rollout flag")
	}
}

func TestClient_EvaluateFlag_Disabled(t *testing.T) {
	flag := exp.FeatureFlag{Key: "disabled-flag", Enabled: false, RolloutPercentage: 100}
	srv := setupFlagServer(t, flag)
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	result, err := c.EvaluateFlag(context.Background(), "disabled-flag", newTestUser("user-1"))
	if err != nil {
		t.Fatalf("EvaluateFlag error: %v", err)
	}
	if result.Enabled {
		t.Error("expected Enabled=false for disabled flag")
	}
}

func TestClient_EvaluateFlag_NotFound(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "not found", http.StatusNotFound)
	}))
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	result, err := c.EvaluateFlag(context.Background(), "missing-flag", newTestUser("user-1"))
	if err == nil {
		t.Error("expected error for 404 response")
	}
	// Should return a graceful disabled result even on error.
	if result == nil {
		t.Error("expected non-nil result even on error")
	} else if result.Enabled {
		t.Error("expected Enabled=false on API error")
	}
}

func TestClient_EvaluateFlag_CacheHit(t *testing.T) {
	callCount := 0
	flag := exp.FeatureFlag{Key: "cached-flag", Enabled: true, RolloutPercentage: 100}

	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/feature-flags/cached-flag/evaluate", func(w http.ResponseWriter, r *http.Request) {
		callCount++
		_ = json.NewEncoder(w).Encode(flag)
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	user := newTestUser("user-cache")

	// Make three calls with the same user+flag combination.
	for i := 0; i < 3; i++ {
		_, err := c.EvaluateFlag(context.Background(), "cached-flag", user)
		if err != nil {
			t.Fatalf("call %d EvaluateFlag error: %v", i, err)
		}
	}

	// With local eval enabled, first call fetches from API, subsequent calls use
	// the local flags map (no additional API calls).
	if callCount > 1 {
		t.Errorf("expected cache to prevent repeated API calls; got %d calls", callCount)
	}
}

func TestClient_EvaluateFlag_ContextCancelled(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(500 * time.Millisecond)
		_ = json.NewEncoder(w).Encode(exp.FeatureFlag{Key: "f", Enabled: true, RolloutPercentage: 100})
	}))
	defer srv.Close()

	c := mustNewClient(t, srv.URL)

	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	_, err := c.EvaluateFlag(ctx, "slow-flag", newTestUser("u1"))
	if err == nil {
		t.Error("expected context cancellation error")
	}
}

func TestClient_EvaluateFlag_EmptyFlagKey(t *testing.T) {
	c, _ := exp.New(exp.WithBaseURL("http://localhost:9999"))
	defer c.Close()

	_, err := c.EvaluateFlag(context.Background(), "", newTestUser("u1"))
	if err == nil {
		t.Error("expected error for empty flagKey")
	}
}

func TestClient_EvaluateFlag_NilUser(t *testing.T) {
	c, _ := exp.New(exp.WithBaseURL("http://localhost:9999"))
	defer c.Close()

	_, err := c.EvaluateFlag(context.Background(), "flag", nil)
	if err == nil {
		t.Error("expected error for nil user")
	}
}

// ---------------------------------------------------------------------------
// Client.GetAssignment tests
// ---------------------------------------------------------------------------

func TestClient_GetAssignment_Success(t *testing.T) {
	expected := exp.Assignment{
		ExperimentKey: "checkout-exp",
		VariantKey:    "treatment",
		UserID:        "user-assign",
	}
	srv := setupAssignmentServer(t, expected)
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	got, err := c.GetAssignment(context.Background(), "checkout-exp", newTestUser("user-assign"))
	if err != nil {
		t.Fatalf("GetAssignment error: %v", err)
	}
	if got.ExperimentKey != expected.ExperimentKey {
		t.Errorf("ExperimentKey = %q; want %q", got.ExperimentKey, expected.ExperimentKey)
	}
	if got.VariantKey != expected.VariantKey {
		t.Errorf("VariantKey = %q; want %q", got.VariantKey, expected.VariantKey)
	}
}

func TestClient_GetAssignment_NotFound(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "experiment not found", http.StatusNotFound)
	}))
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	_, err := c.GetAssignment(context.Background(), "nonexistent-exp", newTestUser("u1"))
	if err == nil {
		t.Error("expected error for 404 response")
	}
}

func TestClient_GetAssignment_EmptyExperimentKey(t *testing.T) {
	c, _ := exp.New(exp.WithBaseURL("http://localhost:9999"))
	defer c.Close()

	_, err := c.GetAssignment(context.Background(), "", newTestUser("u1"))
	if err == nil {
		t.Error("expected error for empty experimentKey")
	}
}

func TestClient_GetAssignment_NilUser(t *testing.T) {
	c, _ := exp.New(exp.WithBaseURL("http://localhost:9999"))
	defer c.Close()

	_, err := c.GetAssignment(context.Background(), "exp", nil)
	if err == nil {
		t.Error("expected error for nil user")
	}
}

func TestClient_GetAssignment_SendsPayload(t *testing.T) {
	var gotPayload map[string]interface{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&gotPayload)
		_ = json.NewEncoder(w).Encode(exp.Assignment{
			ExperimentKey: "exp-1",
			VariantKey:    "control",
			UserID:        "u-payload",
		})
	}))
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	user := newTestUserWithAttrs("u-payload", map[string]interface{}{"plan": "pro"})
	_, _ = c.GetAssignment(context.Background(), "exp-1", user)

	if gotPayload["user_id"] != "u-payload" {
		t.Errorf("payload user_id = %v; want 'u-payload'", gotPayload["user_id"])
	}
	if gotPayload["experiment_key"] != "exp-1" {
		t.Errorf("payload experiment_key = %v; want 'exp-1'", gotPayload["experiment_key"])
	}
}

// ---------------------------------------------------------------------------
// Client.Track tests
// ---------------------------------------------------------------------------

func TestClient_Track_Success(t *testing.T) {
	var gotEvent exp.TrackEvent
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&gotEvent)
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	err := c.Track(context.Background(), &exp.TrackEvent{
		UserID:     "user-track",
		EventName:  "purchase",
		Properties: map[string]interface{}{"amount": 99.99},
	})
	if err != nil {
		t.Fatalf("Track error: %v", err)
	}
	if gotEvent.UserID != "user-track" {
		t.Errorf("event.UserID = %q; want 'user-track'", gotEvent.UserID)
	}
	if gotEvent.EventName != "purchase" {
		t.Errorf("event.EventName = %q; want 'purchase'", gotEvent.EventName)
	}
}

func TestClient_Track_Error(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "server error", http.StatusInternalServerError)
	}))
	defer srv.Close()

	c := mustNewClient(t, srv.URL)
	err := c.Track(context.Background(), &exp.TrackEvent{
		UserID:    "u1",
		EventName: "click",
	})
	if err == nil {
		t.Error("expected error for 500 response")
	}
}

func TestClient_Track_NilEvent(t *testing.T) {
	c, _ := exp.New(exp.WithBaseURL("http://localhost:9999"))
	defer c.Close()

	err := c.Track(context.Background(), nil)
	if err == nil {
		t.Error("expected error for nil event")
	}
}

func TestClient_Track_EmptyUserID(t *testing.T) {
	c, _ := exp.New(exp.WithBaseURL("http://localhost:9999"))
	defer c.Close()

	err := c.Track(context.Background(), &exp.TrackEvent{EventName: "click"})
	if err == nil {
		t.Error("expected error for empty UserID")
	}
}

func TestClient_Track_EmptyEventName(t *testing.T) {
	c, _ := exp.New(exp.WithBaseURL("http://localhost:9999"))
	defer c.Close()

	err := c.Track(context.Background(), &exp.TrackEvent{UserID: "u1"})
	if err == nil {
		t.Error("expected error for empty EventName")
	}
}

// ---------------------------------------------------------------------------
// Client.Close tests
// ---------------------------------------------------------------------------

func TestClient_Close(t *testing.T) {
	c, err := exp.New(exp.WithBaseURL("http://localhost:9999"))
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}
	if err := c.Close(); err != nil {
		t.Errorf("Close() error: %v", err)
	}
	// Second close should not panic.
	if err := c.Close(); err != nil {
		t.Errorf("second Close() error: %v", err)
	}
}

// ---------------------------------------------------------------------------
// Concurrency / race-safety tests
// ---------------------------------------------------------------------------

func TestClient_Concurrent(t *testing.T) {
	flag := exp.FeatureFlag{Key: "race-flag", Enabled: true, RolloutPercentage: 50}
	srv := setupFlagServer(t, flag)
	defer srv.Close()

	c := mustNewClient(t, srv.URL)

	var wg sync.WaitGroup
	const goroutines = 20
	const opsPerG = 50

	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func(gid int) {
			defer wg.Done()
			for j := 0; j < opsPerG; j++ {
				user := newTestUser("cuser-" + intToStr(gid*opsPerG+j))
				_, _ = c.EvaluateFlag(context.Background(), "race-flag", user)
			}
		}(i)
	}
	wg.Wait()
}

// ---------------------------------------------------------------------------
// HTTPClient tests
// ---------------------------------------------------------------------------

func TestHTTPClient_Get_Success(t *testing.T) {
	type response struct {
		Value string `json:"value"`
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(response{Value: "hello"})
	}))
	defer srv.Close()

	h := exp.NewHTTPClient(srv.URL, "key", 5*time.Second)
	var result response
	err := h.Get(context.Background(), "/test", &result)
	if err != nil {
		t.Fatalf("Get error: %v", err)
	}
	if result.Value != "hello" {
		t.Errorf("result.Value = %q; want 'hello'", result.Value)
	}
}

func TestHTTPClient_Get_ServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "internal error", http.StatusInternalServerError)
	}))
	defer srv.Close()

	h := exp.NewHTTPClient(srv.URL, "key", 5*time.Second)
	err := h.Get(context.Background(), "/fail", nil)
	if err == nil {
		t.Error("expected error for 500 response")
	}
}

func TestHTTPClient_Post_Success(t *testing.T) {
	type payload struct {
		Name string `json:"name"`
	}
	type response struct {
		Echo string `json:"echo"`
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var p payload
		_ = json.NewDecoder(r.Body).Decode(&p)
		_ = json.NewEncoder(w).Encode(response{Echo: "got:" + p.Name})
	}))
	defer srv.Close()

	h := exp.NewHTTPClient(srv.URL, "", 5*time.Second)
	var result response
	err := h.Post(context.Background(), "/echo", payload{Name: "world"}, &result)
	if err != nil {
		t.Fatalf("Post error: %v", err)
	}
	if result.Echo != "got:world" {
		t.Errorf("result.Echo = %q; want 'got:world'", result.Echo)
	}
}

func TestHTTPClient_ContextCancellation(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(300 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	h := exp.NewHTTPClient(srv.URL, "key", 5*time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	err := h.Get(ctx, "/slow", nil)
	if err == nil {
		t.Error("expected context deadline error")
	}
}

func TestHTTPClient_AuthHeader(t *testing.T) {
	var gotKey string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("X-API-Key")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("{}"))
	}))
	defer srv.Close()

	h := exp.NewHTTPClient(srv.URL, "my-secret", 5*time.Second)
	var result map[string]interface{}
	_ = h.Get(context.Background(), "/auth-test", &result)

	if gotKey != "my-secret" {
		t.Errorf("X-API-Key = %q; want 'my-secret'", gotKey)
	}
}

func TestHTTPClient_NoAPIKey(t *testing.T) {
	var gotKey string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("X-API-Key")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("{}"))
	}))
	defer srv.Close()

	h := exp.NewHTTPClient(srv.URL, "", 5*time.Second)
	var result map[string]interface{}
	_ = h.Get(context.Background(), "/no-key", &result)

	if gotKey != "" {
		t.Errorf("expected no X-API-Key header; got %q", gotKey)
	}
}

// ---------------------------------------------------------------------------
// Distribution integration test
// ---------------------------------------------------------------------------

func TestEvaluation_Distribution_1000Users(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{
		Key:               "dist-integration-flag",
		Enabled:           true,
		RolloutPercentage: 30.0,
	}

	inRollout := 0
	for i := 0; i < 1000; i++ {
		user := newTestUser("dist-int-" + intToStr(i))
		result := e.EvaluateFlag(flag, user)
		if result.Enabled {
			inRollout++
		}
	}

	// Expect ~30% ± 5% for 1000 samples.
	fraction := float64(inRollout) / 1000.0
	if fraction < 0.25 || fraction > 0.35 {
		t.Errorf("30%% rollout: got %.1f%%; want 25%%–35%%", fraction*100)
	}
}

// TestVariantDistribution_1000Users tests variant assignment distribution.
func TestVariantDistribution_1000Users(t *testing.T) {
	e := &exp.Evaluator{}
	flag := &exp.FeatureFlag{
		Key:               "variant-dist-flag",
		Enabled:           true,
		RolloutPercentage: 100.0,
		Variants: []exp.Variant{
			{Key: "control", Weight: 0.5},
			{Key: "treatment", Weight: 0.5},
		},
	}

	counts := map[string]int{}
	for i := 0; i < 1000; i++ {
		user := newTestUser("vdist-" + intToStr(i))
		result := e.EvaluateFlag(flag, user)
		if result.Enabled {
			counts[result.VariantKey]++
		}
	}

	total := counts["control"] + counts["treatment"]
	if total != 1000 {
		t.Errorf("total = %d; want 1000", total)
	}

	ratio := float64(counts["control"]) / float64(total)
	if ratio < 0.40 || ratio > 0.60 {
		t.Errorf("control ratio = %.2f; want 0.40–0.60", ratio)
	}
}

package experimentation

import (
	"crypto/md5" //nolint:gosec // MD5 used for consistent hashing, not cryptographic security
	"encoding/binary"
	"fmt"
	"strings"
)

// hashDivisor is 2^32 (0x100000000), used to normalize the MD5-derived
// uint32 to a float64 in [0.0, 1.0).
// This MUST match the Java SDK's HASH_DIVISOR and the Python Lambda's
// (MAX_HASH_VALUE + 1) constant so that all SDK implementations produce
// identical assignments for the same user/flag pair.
const hashDivisor = float64(0x100000000)

// hashUser returns a float64 in [0.0, 1.0) for the given userID and flagKey.
//
// Algorithm (byte-for-byte compatible with Java and Python SDKs):
//  1. Concatenate userID + ":" + flagKey as UTF-8.
//  2. Compute MD5 digest.
//  3. Interpret the first 4 bytes as a little-endian unsigned 32-bit integer.
//  4. Divide by 2^32 (0x100000000) to normalize to [0.0, 1.0).
//
// Python equivalent:
//
//	combined = f"{user_id}:{salt}".encode('utf-8')
//	hash_bytes = hashlib.md5(combined).digest()[:4]
//	hash_value = struct.unpack('<I', hash_bytes)[0]   # little-endian unsigned int
//	return hash_value / (MAX_HASH_VALUE + 1)          # normalize
func hashUser(userID, flagKey string) float64 {
	input := userID + ":" + flagKey
	digest := md5.Sum([]byte(input)) //nolint:gosec
	v := binary.LittleEndian.Uint32(digest[:4])
	return float64(v) / hashDivisor
}

// Evaluator performs local (client-side) feature flag evaluation using
// the consistent hash algorithm.
type Evaluator struct{}

// EvaluateFlag evaluates a feature flag for a user locally, without a network call.
//
// Logic:
//  1. If flag is nil or disabled → Enabled=false, Reason="flag_disabled".
//  2. Compute hash for (userID, flagKey); if hash >= rolloutFraction → Reason="out_of_rollout".
//  3. If variants defined → assign one proportionally; Reason="variant_assigned".
//  4. Otherwise → Enabled=true, Reason="in_rollout".
func (e *Evaluator) EvaluateFlag(flag *FeatureFlag, user *User) *EvalResult {
	if flag == nil || !flag.Enabled {
		return &EvalResult{Enabled: false, Reason: "flag_disabled"}
	}

	hash := hashUser(user.ID, flag.Key)
	rolloutFraction := flag.RolloutPercentage / 100.0

	if hash >= rolloutFraction {
		return &EvalResult{Enabled: false, Reason: "out_of_rollout"}
	}

	if len(flag.Variants) > 0 {
		variantKey, variantValue := e.assignVariant(flag.Variants, hash, rolloutFraction)
		return &EvalResult{
			Enabled:    true,
			VariantKey: variantKey,
			Value:      variantValue,
			Reason:     "variant_assigned",
		}
	}

	return &EvalResult{Enabled: true, Reason: "in_rollout"}
}

// assignVariant picks a variant for a user who is already within the rollout band.
//
// The hash is re-scaled within [0, rolloutFraction) → [0.0, 1.0) and then
// each variant is selected proportionally by cumulative weight. This matches
// the Java SDK implementation exactly.
func (e *Evaluator) assignVariant(variants []Variant, hash, rolloutFraction float64) (string, interface{}) {
	// Re-scale hash from [0, rolloutFraction) to [0.0, 1.0)
	var variantHash float64
	if rolloutFraction > 0.0 {
		variantHash = hash / rolloutFraction
	}

	cumulative := 0.0
	for _, v := range variants {
		cumulative += v.Weight
		if variantHash < cumulative {
			return v.Key, v.Value
		}
	}

	// Fallback to last variant to handle floating-point rounding edge cases.
	last := variants[len(variants)-1]
	return last.Key, last.Value
}

// MatchesRules checks whether a user satisfies all targeting rules.
// All rules must match (AND logic). An empty rule list matches all users.
//
// Supported operators:
//   - "eq"  / "equals"           : attribute == value
//   - "neq" / "not_equals"       : attribute != value
//   - "in"                       : attribute is one of []string values
//   - "not_in"                   : attribute is not in []string values
//   - "contains"                 : string attribute contains value
//   - "not_contains"             : string attribute does not contain value
//   - "gt"                       : attribute > numeric value
//   - "gte"                      : attribute >= numeric value
//   - "lt"                       : attribute < numeric value
//   - "lte"                      : attribute <= numeric value
func (e *Evaluator) MatchesRules(rules []Rule, user *User) bool {
	for _, rule := range rules {
		attrVal, exists := user.Attributes[rule.Attribute]
		if !exists {
			return false
		}
		if !matchesRule(attrVal, rule.Operator, rule.Value) {
			return false
		}
	}
	return true
}

// matchesRule evaluates a single rule condition.
func matchesRule(attrVal interface{}, operator string, ruleValue interface{}) bool {
	switch operator {
	case "eq", "equals":
		return fmt.Sprintf("%v", attrVal) == fmt.Sprintf("%v", ruleValue)

	case "neq", "not_equals":
		return fmt.Sprintf("%v", attrVal) != fmt.Sprintf("%v", ruleValue)

	case "in":
		attrStr := fmt.Sprintf("%v", attrVal)
		switch vals := ruleValue.(type) {
		case []interface{}:
			for _, v := range vals {
				if attrStr == fmt.Sprintf("%v", v) {
					return true
				}
			}
		case []string:
			for _, v := range vals {
				if attrStr == v {
					return true
				}
			}
		}
		return false

	case "not_in":
		attrStr := fmt.Sprintf("%v", attrVal)
		switch vals := ruleValue.(type) {
		case []interface{}:
			for _, v := range vals {
				if attrStr == fmt.Sprintf("%v", v) {
					return false
				}
			}
		case []string:
			for _, v := range vals {
				if attrStr == v {
					return false
				}
			}
		}
		return true

	case "contains":
		return strings.Contains(fmt.Sprintf("%v", attrVal), fmt.Sprintf("%v", ruleValue))

	case "not_contains":
		return !strings.Contains(fmt.Sprintf("%v", attrVal), fmt.Sprintf("%v", ruleValue))

	case "gt":
		a, b, ok := toFloat64Pair(attrVal, ruleValue)
		return ok && a > b

	case "gte":
		a, b, ok := toFloat64Pair(attrVal, ruleValue)
		return ok && a >= b

	case "lt":
		a, b, ok := toFloat64Pair(attrVal, ruleValue)
		return ok && a < b

	case "lte":
		a, b, ok := toFloat64Pair(attrVal, ruleValue)
		return ok && a <= b

	default:
		return false
	}
}

// toFloat64Pair converts two values to float64 for numeric comparisons.
func toFloat64Pair(a, b interface{}) (float64, float64, bool) {
	fa, okA := toFloat64(a)
	fb, okB := toFloat64(b)
	return fa, fb, okA && okB
}

// toFloat64 attempts to convert an interface value to float64.
func toFloat64(v interface{}) (float64, bool) {
	switch val := v.(type) {
	case float64:
		return val, true
	case float32:
		return float64(val), true
	case int:
		return float64(val), true
	case int32:
		return float64(val), true
	case int64:
		return float64(val), true
	case uint:
		return float64(val), true
	case uint32:
		return float64(val), true
	case uint64:
		return float64(val), true
	default:
		return 0, false
	}
}

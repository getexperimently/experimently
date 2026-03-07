/**
 * Local feature flag evaluator using the cross-SDK consistent hash algorithm.
 *
 * Hash algorithm (byte-for-byte compatible with Go, Java, Python, iOS, Android SDKs):
 *   1. UTF-8 encode `${userId}:${flagKey}`
 *   2. Compute MD5 digest (16 bytes)
 *   3. Read first 4 bytes as little-endian uint32
 *   4. Divide by 2^32 (4294967296) to get a float in [0, 1)
 *
 * Reference Go implementation (evaluator.go):
 *   digest := md5.Sum([]byte(input))
 *   v := binary.LittleEndian.Uint32(digest[:4])
 *   return float64(v) / float64(0x100000000)
 */

import { md5 } from './md5';
import type { FeatureFlag, TargetingRule } from './types';

// 2^32 — must match the Go hashDivisor constant
const HASH_DIVISOR = 4294967296;

/**
 * Compute a stable bucket value for a user/flag pair.
 *
 * @param userId  - User identifier
 * @param flagKey - Feature flag key
 * @returns float in [0, 1)
 */
export function hashUser(userId: string, flagKey: string): number {
  const input = `${userId}:${flagKey}`;
  const bytes = md5(input); // Uint8Array of 16 bytes
  const view = new DataView(bytes.buffer);
  const uint32 = view.getUint32(0, true); // little-endian
  return uint32 / HASH_DIVISOR;
}

/**
 * Evaluate a single targeting rule against user attributes.
 *
 * Supported operators match the Go SDK (MatchesRules):
 *   eq / equals, neq / not_equals, in, not_in,
 *   contains, not_contains, gt, gte, lt, lte
 */
export function matchesRule(rule: TargetingRule, attributes: Record<string, unknown>): boolean {
  const attrVal = attributes[rule.attribute];
  if (attrVal === undefined) return false;

  const { operator, value: ruleValue } = rule;
  const attrStr = String(attrVal);

  switch (operator) {
    case 'eq':
    case 'equals':
      return attrStr === String(ruleValue);

    case 'neq':
    case 'not_equals':
      return attrStr !== String(ruleValue);

    case 'in': {
      const list = Array.isArray(ruleValue) ? ruleValue : [];
      return list.some((v) => attrStr === String(v));
    }

    case 'not_in': {
      const list = Array.isArray(ruleValue) ? ruleValue : [];
      return !list.some((v) => attrStr === String(v));
    }

    case 'contains':
      return attrStr.includes(String(ruleValue));

    case 'not_contains':
      return !attrStr.includes(String(ruleValue));

    case 'gt': {
      const a = Number(attrVal), b = Number(ruleValue);
      return !isNaN(a) && !isNaN(b) && a > b;
    }

    case 'gte': {
      const a = Number(attrVal), b = Number(ruleValue);
      return !isNaN(a) && !isNaN(b) && a >= b;
    }

    case 'lt': {
      const a = Number(attrVal), b = Number(ruleValue);
      return !isNaN(a) && !isNaN(b) && a < b;
    }

    case 'lte': {
      const a = Number(attrVal), b = Number(ruleValue);
      return !isNaN(a) && !isNaN(b) && a <= b;
    }

    default:
      return false;
  }
}

/**
 * Evaluate a feature flag for a user locally (zero network calls).
 *
 * Logic (matches Go SDK EvaluateFlag):
 *   1. Flag disabled → false
 *   2. Compute hash for (userId, flagKey)
 *   3. If targeting rules exist:
 *        - Find first matching rule → use rule's rolloutPercentage (if set) or flag's
 *        - No rule matches → false
 *   4. Apply global rollout: hash < rolloutPercentage/100 → true
 *
 * @param flag       - Feature flag definition
 * @param userId     - User identifier
 * @param attributes - User attributes for targeting rule evaluation
 * @returns boolean — whether the flag is enabled for this user
 */
export function evaluateFlag(
  flag: FeatureFlag,
  userId: string,
  attributes: Record<string, unknown> = {},
): boolean {
  if (!flag.enabled) return false;

  const bucket = hashUser(userId, flag.key);

  if (flag.rules && flag.rules.length > 0) {
    for (const rule of flag.rules) {
      if (matchesRule(rule, attributes)) {
        // Rule matched: use rule-specific rollout if defined, else flag's global rollout
        const pct = (rule.rolloutPercentage !== undefined)
          ? rule.rolloutPercentage
          : flag.rolloutPercentage;
        return bucket < pct / 100;
      }
    }
    // No rule matched → excluded from flag
    return false;
  }

  return bucket < flag.rolloutPercentage / 100;
}

/**
 * Assign a variant to a user within the rollout band.
 *
 * Uses the same rescaling technique as the Go SDK (assignVariant):
 *   variantHash = hash / rolloutFraction  → [0, 1)
 *   pick variant by cumulative weight
 *
 * @param flag   - Feature flag with variants
 * @param userId - User identifier
 * @returns variant key or null if flag is disabled / user is outside rollout
 */
export function assignVariant(flag: FeatureFlag, userId: string): string | null {
  if (!flag.enabled || !flag.variants || flag.variants.length === 0) return null;

  const rolloutFraction = flag.rolloutPercentage / 100;
  const hash = hashUser(userId, flag.key);

  if (hash >= rolloutFraction) return null;

  // Re-scale hash within [0, rolloutFraction) → [0, 1)
  const variantHash = rolloutFraction > 0 ? hash / rolloutFraction : 0;

  let cumulative = 0;
  for (const variant of flag.variants) {
    cumulative += variant.weight;
    if (variantHash < cumulative) return variant.key;
  }

  // Floating-point safety: return last variant
  return flag.variants[flag.variants.length - 1].key;
}

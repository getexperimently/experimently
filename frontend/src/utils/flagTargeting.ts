/**
 * A flag's stored `targeting_rules` on the flag pages.
 *
 * The flag pages use the experiment page's reading of a stored value
 * (`isEditableTargeting`, `targetingPayload`) with the flag builder's operator
 * options, and add one rule of their own: a save sends `targeting_rules` only
 * when the rules were changed. A save that moves only the rollout percentage
 * leaves the stored rules exactly as they are, whatever shape they have.
 */
import { TargetingRules } from '@/types/targeting';
import { isEditableTargeting, isNoRules, targetingPayload } from '@/utils/experimentTargeting';
import { FLAG_OPERATOR_OPTIONS, jsonToRules } from '@/utils/targeting';

/** Whether the flag page's builder can edit `stored` without changing what it means. */
export function isEditableFlagTargeting(stored: unknown): boolean {
  return isEditableTargeting(stored, FLAG_OPERATOR_OPTIONS);
}

/** The builder state the flag page opens with for an editable stored value. */
export function rulesFromStored(stored: unknown): TargetingRules {
  return jsonToRules(isNoRules(stored) ? null : (stored as object));
}

/** Equality of two JSON values, ignoring the order of object keys. */
export function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    return (
      Array.isArray(a) &&
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((item, i) => sameJson(item, b[i]))
    );
  }
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  if (keys.length !== Object.keys(right).length) return false;
  return keys.every((key) => Object.prototype.hasOwnProperty.call(right, key) && sameJson(left[key], right[key]));
}

/**
 * What a flag save sends as `targeting_rules`, or `undefined` to leave it out.
 *
 * - `rules` is null (stored rules shown read-only, not replaced): left out.
 * - `replaced` (the user confirmed "Replace rules"): always sent, even when
 *   the replacement has no groups, which sends `{}` (no rules).
 * - Otherwise: sent only when `targetingPayload(rules, stored)` differs from
 *   the payload of the state the page loaded from `stored`. Comparing with
 *   `stored` itself would always see a change: the payload drops the
 *   builder's group and condition ids and writes an absent logical operator
 *   as AND.
 */
export function targetingToSend(
  rules: TargetingRules | null,
  stored: unknown,
  replaced: boolean,
): Record<string, unknown> | undefined {
  if (rules === null) return undefined;
  const payload = targetingPayload(rules, stored);
  if (replaced) return payload;
  const baseline = targetingPayload(rulesFromStored(stored), stored);
  return sameJson(payload, baseline) ? undefined : payload;
}

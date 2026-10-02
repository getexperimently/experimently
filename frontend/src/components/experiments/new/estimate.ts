/**
 * The Estimate step of guided setup: what the user typed, and the request it
 * becomes.
 *
 * Pure TypeScript. The inputs are percentages as typed (strings, so a half-typed
 * number stays on screen); `buildEstimateQuery` checks them and converts them to
 * the fractions `GET /api/v1/experiments/analysis/sample-size` takes, or says
 * what is wrong. Nothing here ever enters the create request.
 */
import { SampleSizeQuery } from '@/services/experiments';

/** Statistical power offered, as fractions; the first is the default. */
export const POWER_OPTIONS = [0.8, 0.9, 0.95] as const;
/** Two-sided significance levels offered, as fractions; the first is the default. */
export const SIGNIFICANCE_OPTIONS = [0.05, 0.01, 0.1] as const;

export interface EstimateInputs {
  /** Baseline conversion rate, in percent. */
  baselinePct: string;
  /** Minimum detectable effect, RELATIVE, in percent: 5 means 12% -> 12.6%. */
  mdePct: string;
  power: number;
  significance: number;
  /** Users per day, optional. */
  dailyUsers: string;
  /** Share of those users in the experiment, in percent; blank means all of them. */
  sharePct: string;
}

export const INITIAL_ESTIMATE_INPUTS: EstimateInputs = {
  baselinePct: '',
  mdePct: '',
  power: POWER_OPTIONS[0],
  significance: SIGNIFICANCE_OPTIONS[0],
  dailyUsers: '',
  sharePct: '',
};

export type EstimateQueryResult = { ok: true; query: SampleSizeQuery } | { ok: false; problem: string };

export const ESTIMATE_PROBLEMS = {
  variants: 'The estimate needs at least two variants. Add one on the Variants step.',
  baseline: 'Enter a baseline conversion rate between 0.01% and 99.99%.',
  mde: 'Enter a minimum detectable effect of at least 0.1%.',
  ceiling:
    'This baseline raised by this effect reaches 100% or more. Lower the baseline rate or the effect.',
  dailyUsers: 'Daily users must be a whole number of at least 1.',
  share: 'The share of users must be more than 0% and at most 100%.',
  shareWithoutUsers: 'Enter daily users as well, or leave the share blank.',
} as const;

/** A finite number from a typed field, or null for blank or unreadable input. */
function readNumber(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === '') return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/**
 * The sample-size query for these inputs and this many variants, or the first
 * problem with them. A refused input never reaches the API. The endpoint also
 * refuses a treatment rate of 100% or more itself, with a 422 carrying the
 * `ceiling` sentence word for word (a backend test reads it from this file).
 */
export function buildEstimateQuery(inputs: EstimateInputs, variantCount: number): EstimateQueryResult {
  if (variantCount < 2) return { ok: false, problem: ESTIMATE_PROBLEMS.variants };

  const baselinePct = readNumber(inputs.baselinePct);
  if (baselinePct === null || baselinePct < 0.01 || baselinePct > 99.99) {
    return { ok: false, problem: ESTIMATE_PROBLEMS.baseline };
  }
  const mdePct = readNumber(inputs.mdePct);
  if (mdePct === null || mdePct < 0.1) return { ok: false, problem: ESTIMATE_PROBLEMS.mde };

  const baseline = baselinePct / 100;
  const mde = mdePct / 100;
  if (baseline * (1 + mde) >= 1) return { ok: false, problem: ESTIMATE_PROBLEMS.ceiling };

  const query: SampleSizeQuery = {
    baseline_rate: baseline,
    minimum_detectable_effect: mde,
    statistical_power: inputs.power,
    significance_level: inputs.significance,
    variant_count: variantCount,
  };

  const dailyUsersText = inputs.dailyUsers.trim();
  const shareText = inputs.sharePct.trim();
  if (dailyUsersText !== '') {
    const dailyUsers = readNumber(dailyUsersText);
    if (dailyUsers === null || !Number.isInteger(dailyUsers) || dailyUsers < 1) {
      return { ok: false, problem: ESTIMATE_PROBLEMS.dailyUsers };
    }
    query.daily_traffic = dailyUsers;
    // The endpoint estimates a duration only when it gets BOTH numbers, so a
    // blank share means "all of them" rather than "no duration".
    if (shareText === '') {
      query.traffic_allocation = 1;
    } else {
      const share = readNumber(shareText);
      if (share === null || share <= 0 || share > 100) {
        return { ok: false, problem: ESTIMATE_PROBLEMS.share };
      }
      query.traffic_allocation = share / 100;
    }
  } else if (shareText !== '') {
    return { ok: false, problem: ESTIMATE_PROBLEMS.shareWithoutUsers };
  }

  return { ok: true, query };
}

/** Whether every variant has the same share of traffic. */
export function isEvenSplit(allocations: number[]): boolean {
  return allocations.every((a) => (Number(a) || 0) === (Number(allocations[0]) || 0));
}

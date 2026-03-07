/**
 * @experimentation-platform/edge-sdk
 *
 * Edge-compatible SDK for Cloudflare Workers, Vercel Edge Functions,
 * Deno Deploy, and any WinterCG-compatible JavaScript runtime.
 *
 * Key design constraints:
 *  - Zero Node.js built-ins (no `fs`, `crypto`, `Buffer`, `process`)
 *  - Uses Web Crypto API where needed (or pure-JS implementations)
 *  - Works in Cloudflare Workers, Vercel Edge, Deno Deploy, and browsers
 *  - Sub-millisecond evaluation via bootstrap flags
 *
 * Quick start:
 * ```ts
 * import { EdgeExperimentationClient } from '@experimentation-platform/edge-sdk';
 *
 * const client = new EdgeExperimentationClient({
 *   apiKey: 'your-api-key',
 *   bootstrapFlags: flagsFromKv,
 * });
 *
 * // Sync — zero latency
 * const enabled = client.evaluateFlagSync('new-checkout', userId);
 *
 * // Async — fetches on cache miss
 * const enabled2 = await client.evaluateFlag('new-checkout', userId);
 * ```
 */

// Main client
export { EdgeExperimentationClient } from './client';

// Core utilities
export { hashUser, evaluateFlag, assignVariant, matchesRule } from './evaluator';
export { md5, md5Hex } from './md5';
export { EdgeCache } from './cache';

// Types
export type {
  EdgeSdkConfig,
  FeatureFlag,
  FlagVariant,
  TargetingRule,
  Experiment,
  ExperimentVariant,
  BootstrapResponse,
  EvalResult,
  CacheEntry,
} from './types';

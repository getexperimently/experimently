/**
 * Browser example: using ExperimentationProvider with the OpenFeature Web SDK.
 *
 * In a browser environment the built-in `fetch` is available globally.
 * This example demonstrates usage in a React-like component.
 */

import { OpenFeature, EvaluationContext } from '@openfeature/server-sdk';
import { ExperimentationProvider } from '../src/ExperimentationProvider';

// Initialize once at app startup (e.g., in index.tsx / main.ts).
export async function initFeatureFlags(userId: string): Promise<void> {
  const provider = new ExperimentationProvider({
    apiKey: 'your-public-client-api-key',
    baseUrl: 'https://api.yourplatform.com',
    cacheTtlMs: 5 * 60_000, // 5-minute cache
  });

  await OpenFeature.setProviderAndWait(provider);

  // Set a global context that is merged with per-call context.
  await OpenFeature.setContext({
    targetingKey: userId,
  });
}

// Use in a component.
async function renderHomePage(userId: string): Promise<void> {
  const client = OpenFeature.getClient();

  const ctx: EvaluationContext = { targetingKey: userId };

  const showNewHero = await client.getBooleanValue('new-hero-section', false, ctx);
  const heroVariant = await client.getStringValue('hero-experiment', 'control', ctx);

  console.log(`User ${userId}:`);
  console.log(`  new-hero-section: ${showNewHero}`);
  console.log(`  hero-experiment variant: ${heroVariant}`);
}

// Example usage.
initFeatureFlags('browser-user-789')
  .then(() => renderHomePage('browser-user-789'))
  .catch(console.error);

/**
 * Node.js example: using ExperimentationProvider with the OpenFeature Server SDK.
 *
 * Run with ts-node:
 *   ts-node examples/node-example.ts
 */

import { OpenFeature, EvaluationContext } from '@openfeature/server-sdk';
import { ExperimentationProvider } from '../src/ExperimentationProvider';

async function main(): Promise<void> {
  // 1. Create and register the provider.
  const provider = new ExperimentationProvider({
    apiKey: process.env.EP_API_KEY ?? 'your-api-key',
    baseUrl: process.env.EP_BASE_URL ?? 'http://localhost:8000',
    cacheTtlMs: 60_000, // 1-minute cache
    timeout: 5_000,
  });

  await OpenFeature.setProviderAndWait(provider);

  // 2. Get a client.
  const client = OpenFeature.getClient('my-app');

  // 3. Build user context from the authenticated request.
  const userContext: EvaluationContext = {
    targetingKey: 'user-12345',
    attributes: {
      country: 'US',
      plan: 'pro',
      accountAge: 365,
    } as unknown as EvaluationContext['attributes'],
  };

  // 4. Evaluate flags — application code is SDK-agnostic.
  const darkModeEnabled = await client.getBooleanValue('dark-mode', false, userContext);
  console.log('dark-mode enabled:', darkModeEnabled);

  const checkoutVariant = await client.getStringValue('checkout-experiment', 'control', userContext);
  console.log('checkout-experiment variant:', checkoutVariant);

  const maxItems = await client.getNumberValue('cart-max-items', 10, userContext);
  console.log('cart-max-items:', maxItems);

  const config = await client.getObjectValue('feature-config', {}, userContext);
  console.log('feature-config:', config);

  // 5. Clean up.
  await OpenFeature.clearProviders();
}

main().catch(console.error);

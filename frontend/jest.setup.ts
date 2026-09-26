import '@testing-library/jest-dom';
import { webcrypto } from 'crypto';

// jsdom's `crypto` has getRandomValues but no SubtleCrypto; every browser the
// dashboard supports has both (the SSO hand-off hashes with it). Node's Web
// Crypto stands in, and only where jsdom lacks it.
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
}

/**
 * Jest config for the live contract smoke (examples/contract_smoke.test.ts).
 *
 * Separate from the unit-test config in package.json for three reasons:
 *   - it runs under `testEnvironment: node` rather than the `react-native`
 *     preset, so no native modules or Metro are involved — the SDK's client is
 *     plain TypeScript over `fetch`;
 *   - it targets examples/ only, so `npm test` never picks up a test that needs
 *     a running backend;
 *   - AsyncStorage still resolves to the in-memory mock (there is no native
 *     module under Node), which is the SDK's offline-fallback path.
 *
 * Driven by tests/sdk-contract/live/run_live_contract.py; see that file's
 * MANIFEST entry for react-native.
 */
module.exports = {
  testEnvironment: 'node',
  moduleFileExtensions: ['ts', 'tsx', 'js', 'json'],
  transform: {
    '^.+\\.(ts|tsx)$': ['ts-jest', { tsconfig: 'tsconfig.contract.json' }],
  },
  testMatch: ['<rootDir>/examples/contract_smoke.test.ts'],
  moduleNameMapper: {
    '@react-native-async-storage/async-storage':
      '<rootDir>/__mocks__/@react-native-async-storage/async-storage.ts',
  },
  // Cold start plus a handful of round trips against a locally booted backend.
  testTimeout: 60000,
};

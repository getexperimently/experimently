const { enterpriseTreeAvailable } = require('./ee-alias');

// Open-core seam: `./ee-alias.js` owns the rule, this file applies it to jest.
// The mapper value is an array — jest tries each entry and uses the first that
// resolves — so an Enterprise tree gets `src/ee/x` and falls back to the stub
// for anything it does not carry, while a Community run (`src/ee` deleted, or
// EXPERIMENTLY_EDITION=ce) can only ever reach the stub.
const enterprise = enterpriseTreeAvailable();
const eeTargets = enterprise
  ? ['<rootDir>/src/ee/$1', '<rootDir>/src/ee-stub/$1']
  : ['<rootDir>/src/ee-stub/$1'];

module.exports = {
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  transform: {
    '^.+\\.(ts|tsx)$': ['ts-jest', {
      tsconfig: {
        jsx: 'react-jsx',
        module: 'commonjs',
      },
    }],
  },
  moduleNameMapper: {
    // `@ee/…` first: it is the more specific pattern of the two.
    '^@ee/(.*)$': eeTargets,
    '^@/(.*)$': '<rootDir>/src/$1',
    '\\.(css|less|scss|png|jpg|jpeg|gif|svg)$': 'identity-obj-proxy',
    '^recharts$': '<rootDir>/src/__mocks__/recharts.tsx',
  },
  testMatch: ['**/*.test.ts', '**/*.test.tsx'],
  testPathIgnorePatterns: [
    '/node_modules/',
    '/.next/',
    '/out/',
    // Enterprise tests live beside the Enterprise modules; a Community run has
    // neither. (In a real Community build the directory is gone anyway.)
    ...(enterprise ? [] : ['<rootDir>/src/ee/']),
  ],
  collectCoverageFrom: [
    'src/components/**/*.{ts,tsx}',
    'src/services/**/*.{ts,tsx}',
    'src/hooks/**/*.{ts,tsx}',
    'src/contexts/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
  ],
};

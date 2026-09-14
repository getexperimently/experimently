// ESLint flat config for the dashboard.
//
//   npm run lint      → from the repository root:
//                       eslint --config frontend/eslint.config.mjs
//                              frontend/src modules/frontend/src
//                       (exactly what the `lint` CI job runs)
//
// It runs from the repository root because the modules' dashboard tree is
// `modules/frontend/src`, outside this package, and ESLint 9 ignores every
// file outside the config's base path — the config file's directory when
// discovered, the cwd when passed with `--config`. So the base path has to be
// the repository root, and every pattern below is `**/`-anchored to match
// from there. `modules/frontend/src` is absent from a core tree;
// `--no-error-on-unmatched-pattern` lets the same script pass there.
//
// `next lint` is not used, and could not be: it was a thin eslintrc wrapper
// that Next 14 could not drive with a flat config, and Next 16 removed it
// outright. The Next rules themselves are kept by loading
// @next/eslint-plugin-next directly, which is why the Next 16 upgrade needed
// nothing here.
//
// ESLint stays on 9.x because eslint-plugin-react 7.x declares `eslint ^9.7` as
// its peer. ESLint 10 is its own decision, separate from the framework.

import path from "node:path";
import { fileURLToPath } from "node:url";

import js from "@eslint/js";
import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import nextPlugin from "@next/eslint-plugin-next";
import globals from "globals";

// This package's directory, so the Next rules find `src/pages` whatever the
// cwd is (the rule resolves `settings.next.rootDir` itself, not the cwd).
const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url));

export default tseslint.config(
  {
    ignores: [
      "**/node_modules/**",
      "**/.next/**",
      "**/out/**",
      "**/coverage/**",
      "**/playwright-report/**",
      "**/playwright-results/**",
      "**/next-env.d.ts",
      "**/*.d.ts",
    ],
  },

  js.configs.recommended,
  // Type-aware linting is not enabled: it needs a full program per run and would
  // push this job past its one-minute budget. `tsc --noEmit` is the type gate.
  ...tseslint.configs.recommended,

  {
    files: ["**/*.{js,jsx,ts,tsx,mjs,cjs}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    settings: {
      react: { version: "detect" },
      next: { rootDir: FRONTEND_DIR },
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "@next/next": nextPlugin,
    },
    rules: {
      ...react.configs.flat.recommended.rules,
      ...react.configs.flat["jsx-runtime"].rules, // Next injects React
      ...reactHooks.configs.recommended.rules,
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,

      // --- deliberate relaxations, each with a reason -----------------------
      // The API client and chart payloads are `any` at the boundary until the
      // OpenAPI types land; flagging every one of them is noise, not signal.
      "@typescript-eslint/no-explicit-any": "off",
      // Unused arguments are how React event handlers and service stubs are
      // written here; unused *variables* still fail.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          args: "none",
          varsIgnorePattern: "^_",
          caughtErrors: "none",
          ignoreRestSiblings: true,
        },
      ],
      // Prop types are TypeScript interfaces in this codebase.
      "react/prop-types": "off",
      // `<img>` is used for user-supplied and demo art that next/image cannot
      // optimise in a static export (`output: 'export'`).
      "@next/next/no-img-element": "off",
      // Escaped entities inside copy are handled by prettier-free authoring.
      "react/no-unescaped-entities": "off",
    },
  },

  {
    // Tests and mocks: jest globals, and fixtures that assign-then-assert.
    // Matches both trees: frontend/src/tests and modules/frontend/src/tests.
    files: [
      "**/src/tests/**/*.{ts,tsx}",
      "**/src/**/__tests__/**/*.{ts,tsx}",
      "**/src/__mocks__/**/*.{ts,tsx,js}",
      "**/*.test.{ts,tsx}",
    ],
    languageOptions: { globals: { ...globals.jest, ...globals.node } },
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      "@typescript-eslint/no-empty-function": "off",
    },
  },
);

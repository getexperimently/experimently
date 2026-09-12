// ESLint flat config for the dashboard.
//
//   npm run lint      → eslint src      (exactly what the `lint` CI job runs)
//
// `next lint` is deliberately not used: it is a thin eslintrc wrapper that Next
// 14 cannot drive with a flat config, and it is removed in Next 16. The Next
// rules themselves are kept by loading @next/eslint-plugin-next directly.
//
// ESLint stays on 9.x because eslint-plugin-react 7.x declares `eslint ^9.7` as
// its peer; the Next 16 / React 19 migration (P2) bumps the whole set together.

import js from "@eslint/js";
import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import nextPlugin from "@next/eslint-plugin-next";
import globals from "globals";

export default tseslint.config(
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "coverage/**",
      "playwright-report/**",
      "playwright-results/**",
      "next-env.d.ts",
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
    settings: { react: { version: "detect" } },
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
    files: [
      "src/tests/**/*.{ts,tsx}",
      "src/**/__tests__/**/*.{ts,tsx}",
      "src/__mocks__/**/*.{ts,tsx,js}",
      "**/*.test.{ts,tsx}",
    ],
    languageOptions: { globals: { ...globals.jest, ...globals.node } },
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      "@typescript-eslint/no-empty-function": "off",
    },
  },
);

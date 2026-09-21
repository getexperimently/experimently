// ESLint flat config, replacing .eslintrc.json.
//
// Next 16 removed `next lint` -- `next lint` is now read as a directory
// argument and fails with "Invalid project directory provided, no such
// directory: .../lint". The `lint` script therefore calls eslint directly.
//
// This is a faithful translation of what was here before,
// `{"extends": "next/core-web-vitals"}`: the Next recommended and
// core-web-vitals rule sets, loaded from @next/eslint-plugin-next, and nothing
// else. `eslint-config-next` is not used -- it is an eslintrc-format wrapper,
// which is the thing flat config replaces. The dashboard made the same move in
// #144; its config is larger only because it spans two source trees.
import nextPlugin from "@next/eslint-plugin-next";
import tsParser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    ignores: [
      "**/node_modules/**",
      "**/.next/**",
      "**/out/**",
      "**/coverage/**",
      "**/next-env.d.ts",
    ],
  },
  {
    files: ["**/*.{js,jsx,ts,tsx,mjs}"],
    // The parser only. `eslint-config-next` bundled
    // @typescript-eslint/parser, so without it eslint's default parser hits
    // "Parsing error: Unexpected token <" on every .tsx file. None of
    // typescript-eslint's RULE sets are enabled, which keeps this exactly the
    // rule set the old .eslintrc.json selected; `tsc --noEmit` is the type gate.
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    // react-hooks too: `next/core-web-vitals` bundled it, and the source has
    // inline `eslint-disable-next-line react-hooks/exhaustive-deps` comments
    // that are themselves an error when the rule is undefined.
    plugins: { "@next/next": nextPlugin, "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
    },
  },
];

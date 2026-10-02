/**
 * Every SDK in `sdk/`, by directory, with the name the public pages call it.
 *
 * The homepage and the docs hub used to state how many SDKs there were, and
 * the number drifted from `sdk/`, with one SDK missing from the list. So the
 * pages carry no count, and `tests/content/sdks.test.tsx` holds this map to
 * two facts:
 *
 *   1. its keys are exactly the directories under `sdk/`;
 *   2. every display name appears on the rendered homepage and docs hub.
 *
 * Adding an SDK directory therefore fails that test until it is named here and
 * on both pages. The two OpenFeature providers share one display name because
 * both pages describe them together.
 */
export const SDKS: Readonly<Record<string, string>> = {
  android: 'Android',
  dotnet: '.NET',
  edge: 'Edge',
  elixir: 'Elixir',
  flutter: 'Flutter',
  go: 'Go',
  ios: 'iOS',
  java: 'Java',
  js: 'JavaScript',
  openfeature: 'OpenFeature',
  'openfeature-python': 'OpenFeature',
  php: 'PHP',
  python: 'Python',
  react: 'React',
  'react-native': 'React Native',
  ruby: 'Ruby',
};

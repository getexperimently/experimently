/**
 * The sample-ratio and Bayesian types in types/results.ts describe exactly the
 * schemas the API snapshot documents (#442): the same keys, and null allowed
 * on exactly the fields the API may send as null. A field renamed on either
 * side fails here rather than rendering as undefined.
 *
 * Each record below is type-checked by ts-jest: it must name every key of its
 * type and nothing else, so a field added to an interface without being listed
 * here (or the reverse) fails to compile. The assertions then hold those lists
 * against `docs/api/openapi-v1.stable.json`.
 */
import fs from 'fs';
import path from 'path';
import {
  BayesianPosteriorResult,
  BayesianResultsResponse,
  BayesianVariantResult,
  ExperimentResultsResponse,
  SrmResult,
} from '@/types/results';

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..');
const STABLE_SNAPSHOT = path.join(REPO_ROOT, 'docs', 'api', 'openapi-v1.stable.json');

type Schema = {
  properties: Record<string, { anyOf?: { type?: string }[]; type?: string }>;
};

function schema(name: string): Schema {
  const spec = JSON.parse(fs.readFileSync(STABLE_SNAPSHOT, 'utf8'));
  return spec.components.schemas[name] as Schema;
}

function nullableIn(name: string): string[] {
  return Object.entries(schema(name).properties)
    .filter(([, p]) => (p.anyOf ?? []).some((option) => option.type === 'null'))
    .map(([key]) => key)
    .sort();
}

type NullableKeys<T> = { [K in keyof T]-?: null extends T[K] ? K : never }[keyof T];
type Every<T> = { [K in keyof T]-?: true };
type Nullable<T> = Record<NullableKeys<T>, true>;

const SRM_KEYS: Every<SrmResult> = {
  chi2: true,
  p_value: true,
  warning: true,
  expected: true,
  observed: true,
};
const SRM_NULLABLE: Nullable<SrmResult> = {};

const BAYESIAN_KEYS: Every<BayesianResultsResponse> = {
  is_enabled: true,
  decision: true,
  variant_results: true,
  seed: true,
  n_samples: true,
  engine_version: true,
};
const BAYESIAN_NULLABLE: Nullable<BayesianResultsResponse> = {
  decision: true,
  seed: true,
  n_samples: true,
};

const VARIANT_KEYS: Every<BayesianVariantResult> = {
  variant_key: true,
  posterior: true,
  probability_to_be_best: true,
  expected_loss: true,
  bayes_factor: true,
};
const VARIANT_NULLABLE: Nullable<BayesianVariantResult> = { bayes_factor: true };

const POSTERIOR_KEYS: Every<BayesianPosteriorResult> = {
  alpha: true,
  beta: true,
  mean: true,
  credible_interval_lower: true,
  credible_interval_upper: true,
};
const POSTERIOR_NULLABLE: Nullable<BayesianPosteriorResult> = {};

const CASES: [string, Record<string, true>, Record<string, true>][] = [
  ['SRMResult', SRM_KEYS, SRM_NULLABLE],
  ['BayesianResultsResponse', BAYESIAN_KEYS, BAYESIAN_NULLABLE],
  ['BayesianVariantResult', VARIANT_KEYS, VARIANT_NULLABLE],
  ['BayesianPosteriorResult', POSTERIOR_KEYS, POSTERIOR_NULLABLE],
];

describe('the sample-ratio and Bayesian types match the API snapshot', () => {
  it.each(CASES)('%s has exactly the properties of the snapshot schema', (name, keys) => {
    expect(Object.keys(keys).sort()).toEqual(Object.keys(schema(name).properties).sort());
  });

  it.each(CASES)('%s allows null on exactly the properties the snapshot marks nullable', (name, _k, nullable) => {
    expect(Object.keys(nullable).sort()).toEqual(nullableIn(name));
  });

  it('the results response carries both blocks under these names, both nullable', () => {
    const blocks: Record<'srm' | 'bayesian_results', true> = { srm: true, bayesian_results: true };
    const props = schema('ExperimentResultsResponse').properties;
    for (const key of Object.keys(blocks) as (keyof ExperimentResultsResponse)[]) {
      expect(props).toHaveProperty(key);
    }
    const nullable = nullableIn('ExperimentResultsResponse');
    expect(nullable).toEqual(expect.arrayContaining(['srm', 'bayesian_results']));
  });
});

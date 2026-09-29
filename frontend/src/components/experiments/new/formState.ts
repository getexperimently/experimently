/**
 * The new-experiment form's state, validation and request payload.
 *
 * Pure TypeScript with no React: the page (`pages/experiments/new.tsx`) owns
 * one `useReducer` over `ExperimentFormState`, the field components render
 * slices of it, and `buildCreatePayload` turns it into the exact
 * `CreateExperimentRequest` the page sends. Keeping all of that here lets more
 * than one view of the form share it without drifting apart.
 */
import { TargetingRules } from '@/types/targeting';
import { createEmptyRules } from '@/utils/targeting';
import { ExperimentType, MetricType, CreateExperimentRequest } from '@/types/experiments';

export function generateKey(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .substring(0, 64);
}

export interface VariantFormData {
  name: string;
  description: string;
  traffic_allocation: number;
  is_control: boolean;
}

export interface MetricFormData {
  name: string;
  event_name: string;
  metric_type: MetricType;
  is_primary: boolean;
}

export interface ExperimentFormState {
  name: string;
  key: string;
  /** True once the user has typed in the key field; the name then stops rewriting it. */
  keyEdited: boolean;
  description: string;
  hypothesis: string;
  type: ExperimentType;
  rules: TargetingRules;
  variants: VariantFormData[];
  metrics: MetricFormData[];
}

const DEFAULT_VARIANTS: VariantFormData[] = [
  { name: 'Control', description: '', traffic_allocation: 50, is_control: true },
  { name: 'Treatment', description: '', traffic_allocation: 50, is_control: false },
];

const DEFAULT_METRICS: MetricFormData[] = [
  { name: 'Conversion', event_name: 'conversion', metric_type: 'conversion', is_primary: true },
];

/** A fresh copy of the form's starting values. */
export function createInitialFormState(): ExperimentFormState {
  return {
    name: '',
    key: '',
    keyEdited: false,
    description: '',
    hypothesis: '',
    type: 'a_b',
    rules: createEmptyRules(),
    variants: DEFAULT_VARIANTS,
    metrics: DEFAULT_METRICS,
  };
}

export const INITIAL_FORM_STATE: ExperimentFormState = createInitialFormState();

/**
 * Types this form can fully configure.
 *
 * `split_url` needs a `split_url_config` (without it the split-URL path has no
 * URLs to route to) and `bandit` needs `optimization_type != "fixed"` (with the
 * default `fixed` the bandit scheduler skips the experiment forever, so traffic
 * never adapts). This form sends neither field, so it must not offer them —
 * see `backend/app/schemas/experiment.py::ExperimentCreate`.
 */
export const FORM_EXPERIMENT_TYPES: ExperimentType[] = ['a_b', 'mv'];

/** Sum of the variants' traffic allocations, counting a blank or invalid entry as 0. */
export function allocationTotalOf(variants: VariantFormData[]): number {
  return variants.reduce((sum, v) => sum + (Number(v.traffic_allocation) || 0), 0);
}

// --- validation --------------------------------------------------------------
//
// `validateForm` is the client-side mirror of the `ExperimentCreate`
// validators and reports the FIRST problem, in the order name, variants,
// metrics. The three checks below are that function split at its seams, with
// the same messages in the same order, so a view that validates one part at a
// time reports exactly the words the whole-form check would.

export function checkName(name: string): string | null {
  if (!name.trim()) return 'Name is required.';
  return null;
}

export function checkVariants(variants: VariantFormData[]): string | null {
  if (variants.length === 0) return 'Add at least one variant.';
  if (variants.some((v) => !v.name.trim())) return 'Every variant needs a name.';
  if (!variants.some((v) => v.is_control)) return 'One variant must be marked as control.';
  const total = allocationTotalOf(variants);
  if (total !== 100) return `Variant allocations must add up to 100% (currently ${total}%).`;
  return null;
}

export function checkMetrics(metrics: MetricFormData[]): string | null {
  if (metrics.length === 0) return 'Add at least one metric.';
  if (metrics.some((m) => !m.name.trim() || !m.event_name.trim())) {
    return 'Every metric needs a name and an event name.';
  }
  // The API stores one metric per name per experiment and refuses a repeat.
  const names = metrics.map((m) => m.name.trim());
  if (new Set(names).size !== names.length) return 'Metric names must be unique.';
  if (!metrics.some((m) => m.is_primary)) return 'Choose a primary metric.';
  return null;
}

/** Client-side mirror of the `ExperimentCreate` validators; returns the first problem. */
export function validateForm(
  name: string,
  variants: VariantFormData[],
  metrics: MetricFormData[],
): string | null {
  return checkName(name) ?? checkVariants(variants) ?? checkMetrics(metrics);
}

/** The parts of the form, in the order a step-by-step view asks for them. */
export const FORM_STEPS = ['type', 'details', 'variants', 'estimate', 'review'] as const;
export type FormStep = (typeof FORM_STEPS)[number];

/**
 * The first problem with the part of the form one step asks for, or null.
 *
 * `type` always has a valid value and `estimate` sends nothing, so neither can
 * fail; `review` is the whole-form check. Every message is one `validateForm`
 * can return, and the form is valid exactly when every step is.
 */
export function validateStep(step: FormStep, state: ExperimentFormState): string | null {
  switch (step) {
    case 'type':
      return null;
    case 'details':
      return checkName(state.name) ?? checkMetrics(state.metrics);
    case 'variants':
      return checkVariants(state.variants);
    case 'estimate':
      return null;
    case 'review':
      return validateForm(state.name, state.variants, state.metrics);
  }
}

/**
 * The furthest step (an index into `FORM_STEPS`) a step-by-step view may show:
 * the first step that still has a problem, or `review` when none has. A fresh
 * form reaches `details`, because a new experiment has no name yet.
 */
export function maxReachableStep(state: ExperimentFormState): number {
  const review = FORM_STEPS.indexOf('review');
  for (let i = 0; i < review; i += 1) {
    if (validateStep(FORM_STEPS[i], state) !== null) return i;
  }
  return review;
}

// --- payload -----------------------------------------------------------------

/** The `POST /api/v1/experiments` body for the form as it stands. */
export function buildCreatePayload(state: ExperimentFormState): CreateExperimentRequest {
  const { name, key, description, hypothesis, type, rules, variants, metrics } = state;
  const payload: CreateExperimentRequest = {
    name: name.trim(),
    key: (key || generateKey(name)).trim() || undefined,
    description: description.trim() || undefined,
    hypothesis: hypothesis.trim() || undefined,
    experiment_type: type,
    targeting_rules: rules.groups.length > 0 ? (rules as unknown as Record<string, unknown>) : null,
    variants: variants.map((v) => ({
      name: v.name.trim(),
      description: v.description.trim() || undefined,
      is_control: v.is_control,
      traffic_allocation: Number(v.traffic_allocation) || 0,
    })),
    metrics: metrics.map((m) => ({
      name: m.name.trim(),
      event_name: m.event_name.trim(),
      metric_type: m.metric_type,
      is_primary: m.is_primary,
    })),
  };
  return payload;
}

// --- reducer -----------------------------------------------------------------

export type ExperimentFormAction =
  | { type: 'setName'; name: string }
  | { type: 'setKey'; key: string }
  | { type: 'setDescription'; description: string }
  | { type: 'setHypothesis'; hypothesis: string }
  | { type: 'setType'; experimentType: ExperimentType }
  | { type: 'setRules'; rules: TargetingRules }
  | { type: 'addVariant' }
  | { type: 'removeVariant'; index: number }
  | {
      type: 'changeVariant';
      index: number;
      field: keyof VariantFormData;
      value: string | number | boolean;
    }
  | { type: 'setControl'; index: number }
  | { type: 'addMetric' }
  | { type: 'removeMetric'; index: number }
  | { type: 'changeMetric'; index: number; field: keyof MetricFormData; value: string | boolean }
  | { type: 'setPrimary'; index: number };

export function experimentFormReducer(
  state: ExperimentFormState,
  action: ExperimentFormAction,
): ExperimentFormState {
  switch (action.type) {
    case 'setName':
      return {
        ...state,
        name: action.name,
        key: state.keyEdited ? state.key : generateKey(action.name),
      };
    case 'setKey':
      return { ...state, key: action.key, keyEdited: true };
    case 'setDescription':
      return { ...state, description: action.description };
    case 'setHypothesis':
      return { ...state, hypothesis: action.hypothesis };
    case 'setType':
      return { ...state, type: action.experimentType };
    case 'setRules':
      return { ...state, rules: action.rules };

    case 'addVariant':
      return {
        ...state,
        variants: [
          ...state.variants,
          {
            name: `Variant ${state.variants.length}`,
            description: '',
            traffic_allocation: 0,
            is_control: false,
          },
        ],
      };
    case 'removeVariant':
      return { ...state, variants: state.variants.filter((_, i) => i !== action.index) };
    case 'changeVariant':
      return {
        ...state,
        variants: state.variants.map((v, i) =>
          i === action.index ? { ...v, [action.field]: action.value } : v,
        ),
      };
    case 'setControl':
      return {
        ...state,
        variants: state.variants.map((v, i) => ({ ...v, is_control: i === action.index })),
      };

    case 'addMetric':
      return {
        ...state,
        metrics: [
          ...state.metrics,
          {
            name: '',
            event_name: '',
            metric_type: 'conversion',
            is_primary: state.metrics.length === 0,
          },
        ],
      };
    case 'removeMetric': {
      const next = state.metrics.filter((_, i) => i !== action.index);
      if (next.length > 0 && !next.some((m) => m.is_primary)) {
        next[0] = { ...next[0], is_primary: true };
      }
      return { ...state, metrics: next };
    }
    case 'changeMetric':
      return {
        ...state,
        metrics: state.metrics.map((m, i) =>
          i === action.index ? { ...m, [action.field]: action.value } : m,
        ),
      };
    case 'setPrimary':
      return {
        ...state,
        metrics: state.metrics.map((m, i) => ({ ...m, is_primary: i === action.index })),
      };
  }
}

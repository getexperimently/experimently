import {
  buildCreatePayload,
  checkMetrics,
  checkName,
  checkVariants,
  createInitialFormState,
  experimentFormReducer,
  ExperimentFormAction,
  ExperimentFormState,
  FORM_STEPS,
  INITIAL_FORM_STATE,
  MetricFormData,
  validateForm,
  validateStep,
  VariantFormData,
} from '@/components/experiments/new/formState';

const apply = (actions: ExperimentFormAction[], start: ExperimentFormState = createInitialFormState()) =>
  actions.reduce(experimentFormReducer, start);

describe('INITIAL_FORM_STATE', () => {
  it('holds the form defaults: two 50/50 variants, one primary conversion metric, no rules', () => {
    expect(INITIAL_FORM_STATE).toEqual({
      name: '',
      key: '',
      keyEdited: false,
      description: '',
      hypothesis: '',
      type: 'a_b',
      rules: { logical_operator: 'AND', groups: [] },
      variants: [
        { name: 'Control', description: '', traffic_allocation: 50, is_control: true },
        { name: 'Treatment', description: '', traffic_allocation: 50, is_control: false },
      ],
      metrics: [{ name: 'Conversion', event_name: 'conversion', metric_type: 'conversion', is_primary: true }],
    });
  });

  it('createInitialFormState returns a fresh rules object each time', () => {
    expect(createInitialFormState().rules).not.toBe(createInitialFormState().rules);
  });
});

describe('experimentFormReducer', () => {
  it('derives the key from the name until the key is edited', () => {
    let s = apply([{ type: 'setName', name: 'Pricing Page Test' }]);
    expect(s.key).toBe('pricing_page_test');
    s = apply([{ type: 'setKey', key: 'custom-key' }, { type: 'setName', name: 'Another' }], s);
    expect(s).toMatchObject({ name: 'Another', key: 'custom-key', keyEdited: true });
  });

  it('sets description, hypothesis, type and rules', () => {
    const rules = { logical_operator: 'OR' as const, groups: [] };
    const s = apply([
      { type: 'setDescription', description: 'd' },
      { type: 'setHypothesis', hypothesis: 'h' },
      { type: 'setType', experimentType: 'mv' },
      { type: 'setRules', rules },
    ]);
    expect(s).toMatchObject({ description: 'd', hypothesis: 'h', type: 'mv' });
    expect(s.rules).toBe(rules);
  });

  it('adds a variant named after its index with 0% and no control', () => {
    const s = apply([{ type: 'addVariant' }]);
    expect(s.variants[2]).toEqual({ name: 'Variant 2', description: '', traffic_allocation: 0, is_control: false });
  });

  it('changes one variant field, moves control, and removes a variant', () => {
    let s = apply([
      { type: 'addVariant' },
      { type: 'changeVariant', index: 1, field: 'name', value: 'B' },
      { type: 'changeVariant', index: 1, field: 'traffic_allocation', value: 30 },
      { type: 'setControl', index: 2 },
    ]);
    expect(s.variants.map((v) => [v.name, v.traffic_allocation, v.is_control])).toEqual([
      ['Control', 50, false],
      ['B', 30, false],
      ['Variant 2', 0, true],
    ]);
    s = apply([{ type: 'removeVariant', index: 0 }], s);
    expect(s.variants.map((v) => v.name)).toEqual(['B', 'Variant 2']);
  });

  it('a new metric is primary only when it is the first', () => {
    let s = apply([{ type: 'addMetric' }]);
    expect(s.metrics[1]).toEqual({ name: '', event_name: '', metric_type: 'conversion', is_primary: false });
    s = apply([{ type: 'removeMetric', index: 0 }, { type: 'removeMetric', index: 0 }, { type: 'addMetric' }]);
    expect(s.metrics).toEqual([{ name: '', event_name: '', metric_type: 'conversion', is_primary: true }]);
  });

  it('removing the primary metric promotes the first remaining one', () => {
    const s = apply([{ type: 'addMetric' }, { type: 'addMetric' }, { type: 'removeMetric', index: 0 }]);
    expect(s.metrics.map((m) => m.is_primary)).toEqual([true, false]);
  });

  it('removing a non-primary metric leaves the primary where it is', () => {
    const s = apply([{ type: 'addMetric' }, { type: 'addMetric' }, { type: 'setPrimary', index: 2 }, { type: 'removeMetric', index: 0 }]);
    expect(s.metrics.map((m) => m.is_primary)).toEqual([false, true]);
  });

  it('changes one metric field and moves primary', () => {
    const s = apply([
      { type: 'addMetric' },
      { type: 'changeMetric', index: 1, field: 'event_name', value: 'purchase' },
      { type: 'changeMetric', index: 1, field: 'metric_type', value: 'revenue' },
      { type: 'setPrimary', index: 1 },
    ]);
    expect(s.metrics[1]).toEqual({ name: '', event_name: 'purchase', metric_type: 'revenue', is_primary: true });
    expect(s.metrics[0].is_primary).toBe(false);
  });

  it('never mutates the state it is given', () => {
    const start = createInitialFormState();
    const snapshot = JSON.stringify(start);
    apply(
      [
        { type: 'setName', name: 'x' },
        { type: 'addVariant' },
        { type: 'changeVariant', index: 0, field: 'name', value: 'y' },
        { type: 'setControl', index: 1 },
        { type: 'addMetric' },
        { type: 'removeMetric', index: 0 },
        { type: 'changeMetric', index: 0, field: 'name', value: 'z' },
      ],
      start,
    );
    expect(JSON.stringify(start)).toBe(snapshot);
  });
});

// --- validation ------------------------------------------------------------

const V = (over: Partial<VariantFormData> = {}): VariantFormData => ({
  name: 'Control',
  description: '',
  traffic_allocation: 50,
  is_control: true,
  ...over,
});
const M = (over: Partial<MetricFormData> = {}): MetricFormData => ({
  name: 'Conv',
  event_name: 'purchase',
  metric_type: 'conversion',
  is_primary: true,
  ...over,
});

const GOOD_VARIANTS = [V(), V({ name: 'B', is_control: false })];
const GOOD_METRICS = [M()];

const NAME_CASES: Array<[string, string]> = [
  ['X', 'ok'],
  ['   ', 'blank'],
];
const VARIANT_CASES: Array<[VariantFormData[], string]> = [
  [GOOD_VARIANTS, 'ok'],
  [[], 'none'],
  [[V(), V({ name: ' ', is_control: false })], 'unnamed'],
  [[V({ is_control: false }), V({ name: 'B', is_control: false })], 'no control'],
  [[V(), V({ name: 'B', is_control: false, traffic_allocation: 30 })], '80%'],
];
const METRIC_CASES: Array<[MetricFormData[], string]> = [
  [GOOD_METRICS, 'ok'],
  [[], 'none'],
  [[M({ event_name: '' })], 'no event'],
  [[M({ name: '' })], 'no name'],
  [[M({ is_primary: false })], 'no primary'],
];

const TABLE = NAME_CASES.flatMap(([name, n]) =>
  VARIANT_CASES.flatMap(([variants, v]) =>
    METRIC_CASES.map(([metrics, m]) => ({
      label: `name ${n}, variants ${v}, metrics ${m}`,
      state: { ...createInitialFormState(), name, variants, metrics },
    })),
  ),
);

describe('validateForm and its three checks', () => {
  it('keeps every message word for word', () => {
    expect(checkName('')).toBe('Name is required.');
    expect(checkVariants([])).toBe('Add at least one variant.');
    expect(checkVariants([V({ name: '' })])).toBe('Every variant needs a name.');
    expect(checkVariants([V({ is_control: false, traffic_allocation: 100 })])).toBe(
      'One variant must be marked as control.',
    );
    expect(checkVariants([V({ traffic_allocation: 80 })])).toBe(
      'Variant allocations must add up to 100% (currently 80%).',
    );
    expect(checkMetrics([])).toBe('Add at least one metric.');
    expect(checkMetrics([M({ event_name: ' ' })])).toBe('Every metric needs a name and an event name.');
    expect(checkMetrics([M({ is_primary: false })])).toBe('Choose a primary metric.');
  });

  it.each(TABLE)('$label: validateForm is the first of name, variants, metrics', ({ state }) => {
    expect(validateForm(state.name, state.variants, state.metrics)).toBe(
      checkName(state.name) ?? checkVariants(state.variants) ?? checkMetrics(state.metrics),
    );
  });
});

describe('validateStep against validateForm', () => {
  // Review re-runs the whole-form check, so it would make "every step passes"
  // true of any valid form by itself. The invariants below are about the steps
  // that come BEFORE review: those alone must catch everything validateForm does.
  const STEPS_BEFORE_REVIEW = FORM_STEPS.filter((step) => step !== 'review');
  const firstFailingStep = (state: ExperimentFormState) =>
    STEPS_BEFORE_REVIEW.map((step) => validateStep(step, state)).find((p) => p !== null) ?? null;

  it('has the five steps in order', () => {
    expect(FORM_STEPS).toEqual(['type', 'details', 'variants', 'estimate', 'review']);
  });

  it.each(TABLE)('$label: the form is valid exactly when every step before review is', ({ state }) => {
    const whole = validateForm(state.name, state.variants, state.metrics);
    const steps = STEPS_BEFORE_REVIEW.map((step) => validateStep(step, state));
    expect(whole === null).toBe(steps.every((p) => p === null));
  });

  it.each(TABLE)('$label: every step message is one validateForm can give', ({ state }) => {
    const allowed = [checkName(state.name), checkVariants(state.variants), checkMetrics(state.metrics)];
    for (const step of FORM_STEPS) {
      const problem = validateStep(step, state);
      if (problem !== null) expect(allowed).toContain(problem);
    }
  });

  it('review is the whole-form check', () => {
    for (const { state } of TABLE) {
      expect(validateStep('review', state)).toBe(validateForm(state.name, state.variants, state.metrics));
    }
  });

  // Where the form has one problem, or its problems fall in step order, the
  // first failing step names the same problem validateForm does. The single
  // exception is below: details (step 2) asks for metrics before variants
  // (step 3), while validateForm checks variants first.
  const agreeing = TABLE.filter(
    ({ state }) => !(checkName(state.name) === null && checkVariants(state.variants) && checkMetrics(state.metrics)),
  );
  it.each(agreeing)('$label: the first failing step gives validateForm’s message', ({ state }) => {
    expect(firstFailingStep(state)).toBe(validateForm(state.name, state.variants, state.metrics));
  });

  it('with a good name and both variants and metrics wrong, details reports the metrics problem first', () => {
    const disagreeing = TABLE.filter((row) => !agreeing.includes(row));
    expect(disagreeing).toHaveLength(16);
    for (const { state } of disagreeing) {
      expect(firstFailingStep(state)).toBe(checkMetrics(state.metrics));
      expect(validateForm(state.name, state.variants, state.metrics)).toBe(checkVariants(state.variants));
    }
  });
});

// --- payload -------------------------------------------------------------------

describe('buildCreatePayload', () => {
  // The same inputs as the page test "POSTs an ExperimentCreate payload"
  // (experiment-new.test.tsx), and the same expected body.
  const pageTestState = () =>
    apply([
      { type: 'setName', name: 'Pricing Page Test' },
      { type: 'setDescription', description: 'Does the new layout convert?' },
      { type: 'setType', experimentType: 'mv' },
      { type: 'changeVariant', index: 1, field: 'name', value: 'New layout' },
      { type: 'changeMetric', index: 0, field: 'name', value: 'Purchase' },
      { type: 'changeMetric', index: 0, field: 'event_name', value: 'purchase' },
      { type: 'addMetric' },
      { type: 'changeMetric', index: 1, field: 'name', value: 'Revenue' },
      { type: 'changeMetric', index: 1, field: 'event_name', value: 'purchase' },
      { type: 'changeMetric', index: 1, field: 'metric_type', value: 'revenue' },
    ]);

  it('matches the page test literal', () => {
    expect(buildCreatePayload(pageTestState())).toEqual({
      name: 'Pricing Page Test',
      key: 'pricing_page_test',
      description: 'Does the new layout convert?',
      hypothesis: undefined,
      experiment_type: 'mv',
      targeting_rules: null,
      variants: [
        { name: 'Control', description: undefined, is_control: true, traffic_allocation: 50 },
        { name: 'New layout', description: undefined, is_control: false, traffic_allocation: 50 },
      ],
      metrics: [
        { name: 'Purchase', event_name: 'purchase', metric_type: 'conversion', is_primary: true },
        { name: 'Revenue', event_name: 'purchase', metric_type: 'revenue', is_primary: false },
      ],
    });
  });

  it('sends exactly these eight keys and nothing else', () => {
    // toEqual ignores keys whose value is undefined; this does not.
    expect(Object.keys(buildCreatePayload(pageTestState())).sort()).toEqual(
      [
        'name',
        'key',
        'description',
        'hypothesis',
        'experiment_type',
        'targeting_rules',
        'variants',
        'metrics',
      ].sort(),
    );
  });

  it('trims every text field and drops empty optional ones', () => {
    const s = apply([
      { type: 'setName', name: '  Spaced  ' },
      { type: 'setKey', key: '  my_key  ' },
      { type: 'setDescription', description: '   ' },
      { type: 'setHypothesis', hypothesis: '  We believe  ' },
      { type: 'changeVariant', index: 0, field: 'description', value: '  base  ' },
      { type: 'changeMetric', index: 0, field: 'name', value: '  Conv  ' },
      { type: 'changeMetric', index: 0, field: 'event_name', value: '  buy  ' },
    ]);
    const p = buildCreatePayload(s);
    expect(p).toMatchObject({ name: 'Spaced', key: 'my_key', description: undefined, hypothesis: 'We believe' });
    expect(p.variants[0].description).toBe('base');
    expect(p.metrics[0]).toMatchObject({ name: 'Conv', event_name: 'buy' });
  });

  it('falls back to a generated key, and to none when the name has no usable characters', () => {
    const edited = apply([{ type: 'setName', name: 'Checkout CTA' }, { type: 'setKey', key: '' }]);
    expect(buildCreatePayload(edited).key).toBe('checkout_cta');
    expect(buildCreatePayload(apply([{ type: 'setName', name: '!!!' }])).key).toBeUndefined();
  });

  it('sends targeting rules only when there is at least one group, and an unreadable allocation as 0', () => {
    const rules = {
      logical_operator: 'AND' as const,
      groups: [{ id: 'g1', logical_operator: 'AND' as const, conditions: [] }],
    };
    const s = apply([
      { type: 'setRules', rules },
      { type: 'changeVariant', index: 1, field: 'traffic_allocation', value: Number.NaN },
    ]);
    const p = buildCreatePayload(s);
    expect(p.targeting_rules).toBe(rules);
    expect(p.variants[1].traffic_allocation).toBe(0);
  });
});

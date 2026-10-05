/**
 * Fixed error copy, the "rules not valid" mirror and the role rule of the
 * Segments pages (#440 PR D; gates-D D13, D14, D18).
 */
import { ApiError, unreachableMessage } from '@/services/api';
import { RULES_NOT_VALID, rulesProblems, segmentErrorCopy, segmentInUse, usageCount } from '@/utils/segmentErrors';
import { canChangeSegments } from '@/utils/segmentPermissions';
import { segmentRulesAreValid } from '@/utils/segmentRules';

const PLANTED = 'Traceback (most recent call last): sqlalchemy.exc.PLANTED';

describe('segmentErrorCopy (D14)', () => {
  const actions = ['load', 'load-segment', 'create', 'save-rules', 'archive', 'members', 'check', 'preview', 'usage'] as const;

  it.each([400, 403, 404, 409, 422, 429, 500, 502])('never shows the server text of a %i', (status) => {
    for (const action of actions) {
      const err = new ApiError({ status, detail: PLANTED, message: PLANTED });
      const copy = segmentErrorCopy(err, action);
      expect(copy).not.toContain('PLANTED');
      expect(copy).not.toContain('Traceback');
      expect(copy.length).toBeGreaterThan(10);
    }
  });

  it('a structured 409 detail and a 422 list are not shown either', () => {
    const conflict = new ApiError({ status: 409, detail: { code: 'segment_in_use', message: PLANTED } });
    expect(segmentErrorCopy(conflict, 'archive')).not.toContain('PLANTED');
    const invalid = new ApiError({ status: 422, detail: [{ loc: ['body', 'name'], msg: PLANTED }] });
    expect(segmentErrorCopy(invalid, 'create')).not.toContain('PLANTED');
  });

  it('a TypeError gets the dashboard copy, not its message', () => {
    const copy = segmentErrorCopy(new TypeError("Cannot read properties of undefined (reading 'x')"), 'load');
    expect(copy).toBe('Something went wrong in the dashboard. Reload the page and try again.');
  });

  it('an unreachable API gets the existing unreachable copy', () => {
    expect(segmentErrorCopy(new ApiError({ status: 0, detail: PLANTED }), 'load')).toBe(unreachableMessage());
  });

  it('a 403 names the roles that may change segments', () => {
    const copy = segmentErrorCopy(new ApiError({ status: 403, detail: 'You must be the owner' }), 'archive');
    expect(copy).toContain('ADMIN and DEVELOPER');
    expect(copy).not.toContain('owner');
  });

  it('a 5xx carries the request id, which is ours to show', () => {
    const copy = segmentErrorCopy(new ApiError({ status: 500, detail: PLANTED, requestId: 'req-42' }), 'load');
    expect(copy).toContain('Request ID: req-42.');
  });

  it('a 409 from /evaluate says the rules are not valid', () => {
    expect(segmentErrorCopy(new ApiError({ status: 409, detail: PLANTED }), 'check')).toBe(RULES_NOT_VALID);
  });
});

describe('rulesProblems', () => {
  it('keeps only rules problems in the path form, in the builder words', () => {
    const err = new ApiError({
      status: 422,
      detail: [
        { loc: ['body', 'rules'], msg: 'Value error, groups[0].conditions[1].operator: unknown operator' },
        { loc: ['body', 'rules'], msg: PLANTED },
        { loc: ['body', 'name'], msg: 'groups[0].conditions[0].value: x' },
      ],
    });
    expect(rulesProblems(err)).toEqual(['Group 1, Condition 2: unknown operator']);
  });
});

describe('segmentInUse (D17)', () => {
  it('reads the lists of a segment_in_use 409 and nothing else', () => {
    const err = new ApiError({
      status: 409,
      detail: {
        code: 'segment_in_use',
        message: PLANTED,
        feature_flags: [{ id: 'f1', key: 'checkout-v2', name: 'Checkout v2' }, { name: 'no id' }],
        experiments: [{ id: 'e1', key: 'pricing', name: 'Pricing', status: 'paused' }],
      },
    });
    expect(segmentInUse(err)).toEqual({
      flags: [{ id: 'f1', key: 'checkout-v2', name: 'Checkout v2', status: undefined }],
      experiments: [{ id: 'e1', key: 'pricing', name: 'Pricing', status: 'paused' }],
    });
    expect(segmentInUse(new ApiError({ status: 409, detail: 'x' }))).toBeNull();
    expect(usageCount(1, 2)).toBe('1 flag and 2 experiments');
    expect(usageCount(2, 0)).toBe('2 flags');
  });
});

describe('segmentRulesAreValid (D18)', () => {
  const condition = { attribute: 'plan', operator: 'equals', value: 'pro' };

  it('accepts the dashboard shape with flag operators', () => {
    expect(segmentRulesAreValid({ groups: [{ conditions: [condition] }] })).toBe(true);
    expect(segmentRulesAreValid({ logical_operator: 'NOT', groups: [{ logical_operator: 'OR', conditions: [condition] }] })).toBe(true);
  });

  it.each([
    ['the legacy shape', { operator: 'and', conditions: [{ attribute: 'plan', operator: 'eq', value: 'pro' }] }],
    ['the dashboard shape with a legacy operator', { groups: [{ conditions: [{ attribute: 'plan', operator: 'eq', value: 'pro' }] }] }],
    ['no groups', { groups: [] }],
    ['a group with no condition', { groups: [{ conditions: [] }] }],
    ['groups that are not a list', { groups: 'x' }],
    ['a segment operator inside a segment', { groups: [{ conditions: [{ attribute: 'segment', operator: 'in_segment', value: 'x' }] }] }],
    ['an unknown top-level key', { groups: [{ conditions: [condition] }], id: 'r1' }],
    ['null', null],
  ])('refuses %s', (_label, rules) => {
    expect(segmentRulesAreValid(rules)).toBe(false);
  });
});

describe('canChangeSegments (D13)', () => {
  it.each([
    [{ role: 'ADMIN' }, true],
    [{ role: 'DEVELOPER' }, true],
    [{ role: 'ANALYST' }, false],
    [{ role: 'VIEWER' }, false],
    [{ role: 'VIEWER', is_superuser: true }, true],
    [null, false],
    [undefined, false],
  ])('%j -> %s', (user, expected) => {
    expect(canChangeSegments(user)).toBe(expected);
  });
});

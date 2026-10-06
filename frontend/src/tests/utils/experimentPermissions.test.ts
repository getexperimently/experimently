import {
  FLAG_ROLE_NOTE,
  canChangeExperiment,
  canChangeFeatureFlags,
  canCreateExperiment,
} from '@/utils/experimentPermissions';

describe('canChangeExperiment', () => {
  it.each([
    ['ADMIN', true],
    ['DEVELOPER', true],
    ['ANALYST', false],
    ['VIEWER', false],
  ])('a non-superuser %s -> %s', (role, expected) => {
    expect(canChangeExperiment({ role, is_superuser: false })).toBe(expected);
  });

  it('a superuser may change whatever their role', () => {
    expect(canChangeExperiment({ role: 'VIEWER', is_superuser: true })).toBe(true);
    expect(canChangeExperiment({ role: 'ANALYST', is_superuser: true })).toBe(true);
  });

  it('a user with no role or an unknown role may not', () => {
    expect(canChangeExperiment({})).toBe(false);
    expect(canChangeExperiment({ role: null })).toBe(false);
    expect(canChangeExperiment({ role: 'OWNER' })).toBe(false);
    // Roles are matched exactly, as the API sends them.
    expect(canChangeExperiment({ role: 'admin' })).toBe(false);
  });

  it('no session yet keeps the buttons (the API still decides)', () => {
    expect(canChangeExperiment(null)).toBe(true);
    expect(canChangeExperiment(undefined)).toBe(true);
  });

  it('asks the same role question as create for the four built-in roles', () => {
    for (const role of ['ADMIN', 'DEVELOPER', 'ANALYST', 'VIEWER']) {
      expect(canChangeExperiment({ role })).toBe(canCreateExperiment({ role }));
    }
  });
});

describe('canChangeFeatureFlags (#917)', () => {
  it.each([
    ['ADMIN', true],
    ['DEVELOPER', true],
    ['ANALYST', false],
    ['VIEWER', false],
  ])('a non-superuser %s -> %s', (role, expected) => {
    expect(canChangeFeatureFlags({ role, is_superuser: false })).toBe(expected);
  });

  it('a superuser may change whatever their role', () => {
    expect(canChangeFeatureFlags({ role: 'VIEWER', is_superuser: true })).toBe(true);
    expect(canChangeFeatureFlags({ role: 'ANALYST', is_superuser: true })).toBe(true);
  });

  it('a user with no role or an unknown role may not', () => {
    expect(canChangeFeatureFlags({})).toBe(false);
    expect(canChangeFeatureFlags({ role: null })).toBe(false);
    expect(canChangeFeatureFlags({ role: 'OWNER' })).toBe(false);
    // Roles are matched exactly, as the API sends them.
    expect(canChangeFeatureFlags({ role: 'admin' })).toBe(false);
  });

  it('no session yet keeps the controls (the API still decides)', () => {
    expect(canChangeFeatureFlags(null)).toBe(true);
    expect(canChangeFeatureFlags(undefined)).toBe(true);
  });

  it('asks the same role question as the experiment helpers for the four built-in roles', () => {
    for (const role of ['ADMIN', 'DEVELOPER', 'ANALYST', 'VIEWER']) {
      expect(canChangeFeatureFlags({ role })).toBe(canChangeExperiment({ role }));
    }
  });

  it('the note names the roles the helper accepts', () => {
    expect(FLAG_ROLE_NOTE).toBe('Feature flags are created and changed by the ADMIN and DEVELOPER roles.');
  });
});

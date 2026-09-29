import { canChangeExperiment, canCreateExperiment } from '@/utils/experimentPermissions';

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

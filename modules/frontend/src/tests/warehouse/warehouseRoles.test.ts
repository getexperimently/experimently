/**
 * The dashboard's warehouse role table is the API's, action for action.
 *
 * The API pins its own matrix in
 * modules/backend/tests/integration/warehouse/test_roles.py (every route x a
 * non-superuser of each role). This test reads that file and fails if any
 * action's roles differ, or if either side has an action the other lacks, so
 * the dashboard cannot drift into offering a control the API refuses (or
 * hiding one it allows). Both files live under modules/, so they are present
 * or absent together.
 */
import {
  WAREHOUSE_ACTIONS,
  WarehouseActionName,
  can,
  refusal,
  sourceAction,
  warehouseRole,
} from '@modules/services/warehouseRoles';
import { user } from './fixtures';

// Node's own modules, loaded through jest: the modules tree carries no tsconfig
// `paths` entry for Node built-ins (modules-alias.test.ts pins that list).
const fs = jest.requireActual<{ readFileSync(file: string, encoding: 'utf8'): string }>('fs');
const path = jest.requireActual<{ resolve(...parts: string[]): string; join(...parts: string[]): string }>('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..', '..');
const API_ROLE_TEST = path.join(
  REPO_ROOT,
  'modules',
  'backend',
  'tests',
  'integration',
  'warehouse',
  'test_roles.py',
);

const ROLE_SETS: Record<string, string[]> = {
  everyone: ['ADMIN', 'DEVELOPER', 'ANALYST', 'VIEWER'],
  readers: ['ADMIN', 'DEVELOPER', 'ANALYST'],
  editors: ['ADMIN', 'DEVELOPER'],
  admin: ['ADMIN'],
};

/** (action text -> roles) from the API's role test: one entry per case tuple. */
function apiMatrix(source: string): Map<string, string[]> {
  const re =
    /\(\s*"(GET|POST|PUT|DELETE)",\s*f"\{WA\}[^"]*"\s*\),\s*"([^"]+)",\s*(everyone|readers|editors|admin),/g;
  const out = new Map<string, string[]>();
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) {
    const roles = ROLE_SETS[m[3]];
    const seen = out.get(m[2]);
    if (seen && seen.join() !== roles.join()) throw new Error(`conflicting roles for ${m[2]}`);
    out.set(m[2], roles);
  }
  return out;
}

describe('the warehouse role table', () => {
  it('matches the API role test exactly, action for action', () => {
    const api = apiMatrix(fs.readFileSync(API_ROLE_TEST, 'utf8'));
    // Vacuity guard: the API test has 24 cases over 20 distinct actions. A
    // parser that matched nothing would otherwise "agree" with anything.
    expect(api.size).toBe(20);
    const ours = new Map(
      Object.values(WAREHOUSE_ACTIONS).map((a) => [a.text, [...a.roles]] as [string, string[]]),
    );
    expect(Object.fromEntries(ours)).toEqual(Object.fromEntries(api));
  });

  it('parses a changed role set as a difference (the gate can fail)', () => {
    const source = fs.readFileSync(API_ROLE_TEST, 'utf8');
    // Plant the defect the gate exists for: the API lets DEVELOPER create a
    // connection. The parsed matrix must no longer equal ours.
    const planted = source.replace(
      /("Creating a warehouse connection",\s*)admin,/,
      '$1editors,',
    );
    expect(planted).not.toBe(source);
    const api = apiMatrix(planted);
    expect(api.get('Creating a warehouse connection')).toEqual(['ADMIN', 'DEVELOPER']);
    expect(WAREHOUSE_ACTIONS.createConnection.roles).toEqual(['ADMIN']);
  });

  it('counts a superuser as ADMIN, as the API does', () => {
    expect(warehouseRole(user('VIEWER', true))).toBe('ADMIN');
    expect(can(user('VIEWER', true), 'createConnection')).toBe(true);
    expect(warehouseRole(null)).toBeNull();
    expect(can(null, 'listConnectors')).toBe(false);
  });

  it.each([
    ['createConnection', 'ADMIN', true],
    ['createConnection', 'DEVELOPER', false],
    ['viewConnections', 'ANALYST', true],
    ['viewConnections', 'VIEWER', false],
    ['createMetricSource', 'ANALYST', true],
    ['editMetricSource', 'ANALYST', true],
    ['deleteMetricSource', 'ANALYST', false],
    ['createAssignmentSource', 'ANALYST', false],
    ['createAssignmentSource', 'DEVELOPER', true],
    ['viewRuns', 'VIEWER', true],
  ] as [WarehouseActionName, 'ADMIN' | 'DEVELOPER' | 'ANALYST' | 'VIEWER', boolean][])(
    '%s for %s is %s',
    (action, role, expected) => {
      expect(can(user(role), action)).toBe(expected);
    },
  );

  it('words a refusal exactly as the API does', () => {
    expect(refusal(user('DEVELOPER'), 'createConnection')).toBe(
      'Creating a warehouse connection requires the ADMIN role; you are DEVELOPER.',
    );
    expect(refusal(user('VIEWER'), 'viewConnections')).toBe(
      'Viewing warehouse connections requires the ADMIN, DEVELOPER or ANALYST role; you are VIEWER.',
    );
    expect(refusal(null, 'viewSources')).toMatch(/; you have no role\.$/);
  });

  it('names per-kind source actions', () => {
    expect(sourceAction('create', 'metric')).toBe('createMetricSource');
    expect(sourceAction('delete', 'assignment')).toBe('deleteAssignmentSource');
    for (const verb of ['create', 'edit', 'delete', 'validate', 'preview'] as const) {
      for (const kind of ['assignment', 'metric'] as const) {
        expect(WAREHOUSE_ACTIONS[sourceAction(verb, kind)]).toBeDefined();
      }
    }
  });
});

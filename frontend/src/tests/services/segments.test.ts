/**
 * The Segments client sends exactly the calls the API reads (#440 PR D;
 * gates-D D20). Exact `toHaveBeenCalledWith`, never `objectContaining`.
 */
import { apiFetch } from '@/services/api';
import { SegmentsService } from '@/services/segments';

jest.mock('@/services/api', () => ({
  ...jest.requireActual('@/services/api'),
  apiFetch: jest.fn(),
}));

const mocked = apiFetch as jest.MockedFunction<typeof apiFetch>;
const SEG = '3f2b9c1e-8d4a-4c6b-9e2f-1a2b3c4d5e6f';
const RULES = { logical_operator: 'AND', groups: [{ logical_operator: 'AND', conditions: [{ attribute: 'plan', operator: 'equals', value: 'pro' }] }] };

beforeEach(() => {
  mocked.mockReset();
  mocked.mockResolvedValue([] as never);
});

describe('SegmentsService (D20)', () => {
  it('lists one page with status, limit and offset', async () => {
    await SegmentsService.list({ status: 'archived', limit: 50, offset: 100 });
    expect(mocked).toHaveBeenCalledWith('/api/v1/segments', { query: { status: 'archived', limit: 50, offset: 100 } });
  });

  it('lists every status in pages of 200 until a short page', async () => {
    const page = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `s${i}` }));
    mocked.mockResolvedValueOnce(page(200) as never).mockResolvedValueOnce(page(3) as never);
    const all = await SegmentsService.listAll();
    expect(all).toHaveLength(203);
    expect(mocked.mock.calls).toEqual([
      ['/api/v1/segments', { query: { status: undefined, limit: 200, offset: 0 } }],
      ['/api/v1/segments', { query: { status: undefined, limit: 200, offset: 200 } }],
    ]);
  });

  it('creates a rules segment and an id list with the bodies the API reads', async () => {
    await SegmentsService.create({ name: 'Pro', kind: 'rules', rules: RULES });
    await SegmentsService.create({ name: 'Pilot', description: 'CRM export', kind: 'id_list' });
    expect(mocked.mock.calls).toEqual([
      ['/api/v1/segments', { method: 'POST', json: { name: 'Pro', kind: 'rules', rules: RULES } }],
      ['/api/v1/segments', { method: 'POST', json: { name: 'Pilot', description: 'CRM export', kind: 'id_list' } }],
    ]);
  });

  it('reads, saves rules, archives and lists where a segment is used', async () => {
    await SegmentsService.get(SEG);
    await SegmentsService.updateRules(SEG, RULES);
    await SegmentsService.archive(SEG);
    await SegmentsService.usage(SEG);
    expect(mocked.mock.calls).toEqual([
      [`/api/v1/segments/${SEG}`],
      [`/api/v1/segments/${SEG}`, { method: 'PUT', json: { rules: RULES } }],
      [`/api/v1/segments/${SEG}`, { method: 'DELETE' }],
      [`/api/v1/segments/${SEG}/experiments`],
    ]);
  });

  it('checks a user by user_id and previews rules', async () => {
    await SegmentsService.checkUser(SEG, 'cust-1');
    await SegmentsService.preview(SEG, 'Pro', RULES);
    expect(mocked.mock.calls).toEqual([
      [`/api/v1/segments/${SEG}/evaluate`, { method: 'POST', json: { user_context: { user_id: 'cust-1' } } }],
      [`/api/v1/segments/${SEG}/preview`, { method: 'POST', json: { name: 'Pro', kind: 'rules', rules: RULES } }],
    ]);
  });

  it('adds with {add} and removes with {remove}', async () => {
    await SegmentsService.addMembers(SEG, ['a', 'b']);
    await SegmentsService.removeMembers(SEG, ['c']);
    expect(mocked.mock.calls).toEqual([
      [`/api/v1/segments/${SEG}/members`, { method: 'POST', json: { add: ['a', 'b'] } }],
      [`/api/v1/segments/${SEG}/members/remove`, { method: 'POST', json: { remove: ['c'] } }],
    ]);
  });
});

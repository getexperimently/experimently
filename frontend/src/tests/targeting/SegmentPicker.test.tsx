/**
 * The segment picker in the rule builder (#440 PR D; gates-D D8-D11, D21).
 *
 * The row kind is decided by the operator (U2); stored segments that are not
 * active stay named, with the fail-closed warning; a ruleset may name at most
 * 10 segments; a segment's own rules offer no segment operator.
 */
import React, { useState } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axe from 'axe-core';
import { TargetingRuleBuilder } from '@/components/targeting';
import { UNAVAILABLE_SEGMENT_WARNING } from '@/components/targeting/SegmentPicker';
import { Segment, SegmentsService } from '@/services/segments';
import { TargetingCondition, TargetingRules } from '@/types/targeting';
import { isEditableTargeting } from '@/utils/experimentTargeting';
import { isEditableFlagTargeting } from '@/utils/flagTargeting';
import { FLAG_OPERATOR_OPTIONS, OperatorOptions, SEGMENT_RULES_OPERATOR_OPTIONS, getOperatorsForAttribute } from '@/utils/targeting';

jest.mock('@/services/segments', () => ({
  ...jest.requireActual('@/services/segments'),
  SegmentsService: { listAll: jest.fn() },
}));

jest.mock('next/link', () => {
  const Link = ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  );
  Link.displayName = 'MockLink';
  return Link;
});

const listAll = SegmentsService.listAll as jest.Mock;

const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

function segment(n: number, overrides: Partial<Segment> = {}): Segment {
  return {
    id: uuid(n),
    name: `Segment ${String(n).padStart(2, '0')}`,
    kind: n % 2 ? 'id_list' : 'rules',
    rules: n % 2 ? null : { groups: [{ conditions: [{ attribute: 'plan', operator: 'equals', value: 'pro' }] }] },
    status: 'active',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
  };
}

function cond(id: string, attribute: string, operator: string, value: TargetingCondition['value']): TargetingCondition {
  return { id, attribute, operator: operator as TargetingCondition['operator'], value };
}

function rulesOf(...conditions: TargetingCondition[]): TargetingRules {
  return { logical_operator: 'AND', groups: [{ id: 'g1', logical_operator: 'OR', conditions }] };
}

function Harness({ initial, options }: { initial: TargetingRules; options?: OperatorOptions }) {
  const [rules, setRules] = useState(initial);
  return (
    <>
      <TargetingRuleBuilder value={rules} onChange={setRules} operatorOptions={options} />
      <output data-testid="rules-json">{JSON.stringify(rules)}</output>
    </>
  );
}

const axeOptions: axe.RunOptions = { rules: { 'color-contrast': { enabled: false } } };
async function violations(node: Element) {
  const result = await axe.run(node, axeOptions);
  return result.violations.map((v) => `${v.id} (${v.impact})`);
}

beforeEach(() => {
  listAll.mockReset();
  listAll.mockResolvedValue([segment(1), segment(2)]);
});

describe('row kind is decided by the operator (U2, D8)', () => {
  it('keeps `segment equals enterprise` a text condition and loads no segments', async () => {
    render(<Harness initial={rulesOf(cond('c1', 'segment', 'equals', 'enterprise'))} />);
    expect(screen.getByLabelText('Group 1, condition 1 operator')).toHaveValue('equals');
    expect(screen.getByLabelText('Group 1, condition 1 value')).toHaveValue('enterprise');
    expect(screen.queryByTestId('condition-segment')).toBeNull();
    expect(listAll).not.toHaveBeenCalled();
  });

  it('shows a select named "Group 1, condition 1 segment" for in_segment', async () => {
    render(<Harness initial={rulesOf(cond('c1', 'segment', 'in_segment', uuid(1)))} />);
    const select = await screen.findByRole('combobox', { name: 'Group 1, condition 1 segment' });
    await waitFor(() => expect(select).not.toBeDisabled());
    expect(select).toHaveValue(uuid(1));
    expect(screen.queryByLabelText('Group 1, condition 1 value')).toBeNull();
    const labels = within(select).getAllByRole('option').map((o) => o.textContent);
    expect(labels).toEqual(['Choose a segment', 'Segment 01 · ID list', 'Segment 02 · Rules']);
    expect(listAll).toHaveBeenCalledTimes(1);
  });

  it('switching to a segment operator clears the text value, and back again', async () => {
    render(<Harness initial={rulesOf(cond('c1', 'segment', 'equals', 'enterprise'))} />);
    fireEvent.change(screen.getByLabelText('Group 1, condition 1 operator'), { target: { value: 'not_in_segment' } });
    const select = await screen.findByRole('combobox', { name: 'Group 1, condition 1 segment' });
    await waitFor(() => expect(select).not.toBeDisabled());
    fireEvent.change(select, { target: { value: uuid(2) } });
    expect(JSON.parse(screen.getByTestId('rules-json').textContent ?? '{}').groups[0].conditions[0]).toMatchObject({
      attribute: 'segment',
      operator: 'not_in_segment',
      value: uuid(2),
    });
    fireEvent.change(screen.getByLabelText('Group 1, condition 1 operator'), { target: { value: 'equals' } });
    expect(screen.getByLabelText('Group 1, condition 1 value')).toHaveValue('');
  });

  it('offers the segment operators on the attribute `segment` only', () => {
    expect(getOperatorsForAttribute('segment')).toEqual(expect.arrayContaining(['equals', 'in_segment', 'not_in_segment']));
    expect(getOperatorsForAttribute('segment', FLAG_OPERATOR_OPTIONS)).toContain('in_segment');
    expect(getOperatorsForAttribute('user.plan')).not.toContain('in_segment');
    expect(getOperatorsForAttribute('plan', FLAG_OPERATOR_OPTIONS)).not.toContain('in_segment');
  });
});

describe('a segment rules builder offers no segment operator (D11)', () => {
  it('leaves the operators out and the datalist suggestion too', () => {
    expect(getOperatorsForAttribute('segment', SEGMENT_RULES_OPERATOR_OPTIONS)).not.toContain('in_segment');
    const { container } = render(
      <Harness initial={rulesOf(cond('c1', 'segment', 'equals', 'x'))} options={SEGMENT_RULES_OPERATOR_OPTIONS} />,
    );
    const operators = within(screen.getByLabelText('Group 1, condition 1 operator')).getAllByRole('option').map((o) => o.getAttribute('value'));
    expect(operators).not.toContain('in_segment');
    expect(operators).not.toContain('not_in_segment');
    expect(container.querySelector('datalist option[value="segment"]')).toBeNull();
  });
});

describe('isEditableTargeting accepts segment conditions (D9)', () => {
  const stored = (operator: string, value: unknown, attribute = 'segment') => ({
    logical_operator: 'AND',
    groups: [{ logical_operator: 'AND', conditions: [{ attribute, operator, value }] }],
  });

  it.each(['in_segment', 'not_in_segment'])('%s with a segment id is editable on experiment and flag pages', (op) => {
    expect(isEditableTargeting(stored(op, uuid(1)))).toBe(true);
    expect(isEditableFlagTargeting(stored(op, uuid(1)))).toBe(true);
  });

  it('is not editable in a segment builder, on another attribute, or with a value that is not a segment id', () => {
    expect(isEditableTargeting(stored('in_segment', uuid(1)), SEGMENT_RULES_OPERATOR_OPTIONS)).toBe(false);
    expect(isEditableTargeting(stored('in_segment', uuid(1), 'plan'))).toBe(false);
    expect(isEditableTargeting(stored('in_segment', '3f2b9c1e-8d4a-4c6b-9e2f-1a2b3c4d5e6f'))).toBe(true);
    expect(isEditableTargeting(stored('in_segment', '3F2B9C1E-8D4A-4C6B-9E2F-1A2B3C4D5E6F'))).toBe(false);
    expect(isEditableTargeting(stored('in_segment', 'enterprise'))).toBe(false);
    expect(isEditableTargeting(stored('in_segment', [uuid(1)]))).toBe(false);
  });
});

describe('picker states (D10)', () => {
  it.each([
    ['unknown', [segment(1)], uuid(99), 'Unknown segment (deleted or from another installation)'],
    ['archived', [segment(1), segment(3, { status: 'archived', name: 'Pilot' })], uuid(3), 'Archived segment: Pilot'],
    ['inactive', [segment(1), segment(3, { status: 'inactive', name: 'Pilot' })], uuid(3), 'Inactive segment: Pilot'],
  ])('a stored %s segment keeps its name and the fail-closed warning', async (_label, list, value, label) => {
    listAll.mockResolvedValue(list);
    const { container } = render(<Harness initial={rulesOf(cond('c1', 'segment', 'in_segment', value))} />);
    const warning = await screen.findByTestId('segment-picker-unavailable');
    expect(warning).toHaveTextContent(UNAVAILABLE_SEGMENT_WARNING);
    const select = screen.getByRole('combobox', { name: 'Group 1, condition 1 segment' });
    expect(select).toHaveValue(value);
    expect((select as HTMLSelectElement).selectedOptions[0].textContent).toBe(label);
    expect(await violations(container)).toEqual([]);
  });

  it('the warning never says a condition matches every user', () => {
    expect(UNAVAILABLE_SEGMENT_WARNING).not.toMatch(/matches every user|convert/i);
  });

  it('with 10 segments named, an unused one is disabled and the reason is in text', async () => {
    listAll.mockResolvedValue(Array.from({ length: 12 }, (_, i) => segment(i + 1)));
    const conditions = Array.from({ length: 10 }, (_, i) => cond(`c${i}`, 'segment', 'in_segment', uuid(i + 1)));
    const { container } = render(<Harness initial={rulesOf(...conditions)} />);
    const select = await screen.findByRole('combobox', { name: 'Group 1, condition 1 segment' });
    await waitFor(() => expect(select).not.toBeDisabled());
    const option11 = within(select).getByRole('option', { name: /Segment 11/ }) as HTMLOptionElement;
    expect(option11.disabled).toBe(true);
    expect(option11.textContent).toContain('(limit of 10 segments reached)');
    const option2 = within(select).getByRole('option', { name: /Segment 02/ }) as HTMLOptionElement;
    expect(option2.disabled).toBe(false);
    expect(screen.getAllByTestId('segment-picker-limit')[0]).toHaveTextContent('A ruleset can use at most 10 segments.');
    expect(await violations(container)).toEqual([]);
  });

  it('with 9 named, nothing is disabled', async () => {
    listAll.mockResolvedValue(Array.from({ length: 12 }, (_, i) => segment(i + 1)));
    const conditions = Array.from({ length: 9 }, (_, i) => cond(`c${i}`, 'segment', 'in_segment', uuid(i + 1)));
    render(<Harness initial={rulesOf(...conditions)} />);
    const select = await screen.findByRole('combobox', { name: 'Group 1, condition 1 segment' });
    await waitFor(() => expect(select).not.toBeDisabled());
    expect((within(select).getByRole('option', { name: /Segment 11/ }) as HTMLOptionElement).disabled).toBe(false);
    expect(screen.queryByTestId('segment-picker-limit')).toBeNull();
  });

  it('a segment whose rules are not valid cannot be chosen', async () => {
    listAll.mockResolvedValue([segment(2, { rules: { groups: [] }, name: 'Old' })]);
    render(<Harness initial={rulesOf(cond('c1', 'segment', 'in_segment', ''))} />);
    const select = await screen.findByRole('combobox', { name: 'Group 1, condition 1 segment' });
    await waitFor(() => expect(select).not.toBeDisabled());
    const old = within(select).getByRole('option', { name: /Old/ }) as HTMLOptionElement;
    expect(old.disabled).toBe(true);
    expect(old.textContent).toContain('(rules not valid)');
  });

  it('a failed load offers Retry and the builder stays usable', async () => {
    listAll.mockRejectedValueOnce(new Error('PLANTED')).mockResolvedValueOnce([segment(1)]);
    const { container } = render(<Harness initial={rulesOf(cond('c1', 'segment', 'in_segment', ''))} />);
    expect(await screen.findByTestId('segment-picker-error')).toHaveTextContent("Couldn't load segments.");
    expect(document.body.textContent).not.toContain('PLANTED');
    expect(screen.getByTestId('add-condition')).toBeEnabled();
    expect(await violations(container)).toEqual([]);
    fireEvent.click(screen.getByTestId('segment-picker-retry'));
    const select = screen.getByRole('combobox', { name: 'Group 1, condition 1 segment' });
    await waitFor(() => expect(select).not.toBeDisabled());
    expect(listAll).toHaveBeenCalledTimes(2);
  });

  it('no active segment links to the Segments page', async () => {
    listAll.mockResolvedValue([segment(3, { status: 'archived' })]);
    const { container } = render(<Harness initial={rulesOf(cond('c1', 'segment', 'in_segment', ''))} />);
    const empty = await screen.findByTestId('segment-picker-empty');
    expect(within(empty).getByRole('link')).toHaveAttribute('href', '/segments/new');
    expect(empty).toHaveTextContent('opens in a new tab');
    expect(await violations(container)).toEqual([]);
  });

  it('read-only rows show the name and no controls that change anything', async () => {
    render(<TargetingRuleBuilder value={rulesOf(cond('c1', 'segment', 'in_segment', uuid(1)))} onChange={() => undefined} readOnly />);
    const select = await screen.findByRole('combobox', { name: 'Group 1, condition 1 segment' });
    await waitFor(() => expect((select as HTMLSelectElement).selectedOptions[0].textContent).toBe('Segment 01 · ID list'));
    expect(select).toBeDisabled();
  });
});

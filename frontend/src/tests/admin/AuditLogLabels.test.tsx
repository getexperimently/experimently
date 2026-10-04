import React from 'react';
import { render, screen, within } from '@testing-library/react';
import actionTypes from '@/components/admin/audit/action-types.json';
import {
  ACTIONS,
  actionFilterGroups,
  actionLabel,
  actorLabel,
} from '@/components/admin/audit/actionLabels';
import { AuditLogFilter } from '@/components/admin/audit/AuditLogFilter';

describe('audit action labels (#221)', () => {
  it('labels exactly the action types the API writes', () => {
    expect(Object.keys(ACTIONS).sort()).toStrictEqual([...actionTypes].sort());
    for (const type of actionTypes) {
      expect(actionLabel(type)).not.toBe(type);
    }
  });

  it('puts every written type in exactly one filter group', () => {
    const grouped = actionFilterGroups().flatMap((g) => g.options.map((o) => o.value));
    expect([...grouped].sort()).toStrictEqual([...actionTypes].sort());
    expect(new Set(grouped).size).toBe(grouped.length);
  });

  it('shows an unknown type as itself', () => {
    expect(actionLabel('user_update')).toBe('user_update');
  });
});

describe('the action filter (#221)', () => {
  it('offers All actions, then only the written types, grouped', () => {
    render(<AuditLogFilter filters={{}} onFilterChange={jest.fn()} />);
    const select = screen.getByTestId('filter-action-type');
    const values = Array.from(select.querySelectorAll('option')).map((o) => o.value);
    expect(values[0]).toBe('');
    expect(within(select).getAllByRole('option')[0]).toHaveTextContent('All actions');
    expect(values.slice(1).sort()).toStrictEqual([...actionTypes].sort());
    const groups = Array.from(select.querySelectorAll('optgroup')).map((g) => g.label);
    expect(groups).toStrictEqual([
      'Flags',
      'Experiments',
      'Users and access',
      'Holdouts, groups and segments',
      'Safety',
    ]);
    // Every typed option sits inside a group.
    expect(select.querySelectorAll('optgroup option')).toHaveLength(actionTypes.length);
  });

  it('offers no entity nothing writes', () => {
    render(<AuditLogFilter filters={{}} onFilterChange={jest.fn()} />);
    const values = Array.from(
      screen.getByTestId('filter-entity-type').querySelectorAll('option'),
    ).map((o) => o.value);
    expect(values).not.toContain('safety_config');
    expect(values[0]).toBe('');
  });
});

describe('actorLabel: "(automatic)" only for the platform\'s own actors (#221)', () => {
  it('marks a reserved email with no user_id', () => {
    expect(actorLabel({ user_id: null, user_email: 'system:safety-monitor' })).toBe(
      'Safety monitor (automatic)',
    );
    expect(actorLabel({ user_id: null, user_email: 'system:experiment-scheduler' })).toBe(
      'Experiment scheduler (automatic)',
    );
  });

  it("does not mark a deleted user's entry (no user_id, a real email)", () => {
    expect(actorLabel({ user_id: null, user_email: 'gone@example.com' })).toBe(
      'gone@example.com',
    );
  });

  it('does not mark a reserved email that carries a user_id', () => {
    expect(actorLabel({ user_id: 'u-1', user_email: 'system:safety-monitor' })).toBe(
      'system:safety-monitor',
    );
  });
});

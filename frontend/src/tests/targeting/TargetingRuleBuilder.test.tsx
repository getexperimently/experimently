import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { TargetingRuleBuilder } from '@/components/targeting/TargetingRuleBuilder';
import { TargetingRules } from '@/types/targeting';

const emptyRules: TargetingRules = {
  logical_operator: 'AND',
  groups: [],
};

const rulesWithOneGroup: TargetingRules = {
  logical_operator: 'AND',
  groups: [
    {
      id: 'g1',
      logical_operator: 'AND',
      conditions: [
        { id: 'c1', attribute: 'user.country', operator: 'equals', value: 'US' },
      ],
    },
  ],
};

const rulesWithTwoGroups: TargetingRules = {
  logical_operator: 'OR',
  groups: [
    {
      id: 'g1',
      logical_operator: 'AND',
      conditions: [
        { id: 'c1', attribute: 'user.country', operator: 'equals', value: 'US' },
      ],
    },
    {
      id: 'g2',
      logical_operator: 'AND',
      conditions: [
        { id: 'c2', attribute: 'user.plan', operator: 'equals', value: 'pro' },
        { id: 'c3', attribute: 'user.age', operator: 'greater_than', value: '18' },
      ],
    },
  ],
};

describe('TargetingRuleBuilder', () => {
  it('shows empty state message when rules.groups is empty', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={emptyRules} onChange={onChange} />);
    expect(
      screen.getByText(/No targeting rules.*all users/i)
    ).toBeInTheDocument();
  });

  it('renders "Add Group" button when empty', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={emptyRules} onChange={onChange} />);
    expect(screen.getByTestId('add-group')).toBeInTheDocument();
  });

  it('calls onChange with new group when "Add Group" is clicked', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={emptyRules} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('add-group'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const updatedRules = onChange.mock.calls[0][0] as TargetingRules;
    expect(updatedRules.groups).toHaveLength(1);
  });

  it('renders each group as a card', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={rulesWithTwoGroups} onChange={onChange} />);
    expect(screen.getByText(/Group 1/i)).toBeInTheDocument();
    expect(screen.getByText(/Group 2/i)).toBeInTheDocument();
  });

  it('shows top-level AND/OR toggle', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={rulesWithOneGroup} onChange={onChange} />);
    expect(screen.getByTestId('root-logical-and')).toBeInTheDocument();
    expect(screen.getByTestId('root-logical-or')).toBeInTheDocument();
  });

  it('calls onChange with updated logical_operator when top-level toggle changes', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={rulesWithOneGroup} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('root-logical-or'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const updatedRules = onChange.mock.calls[0][0] as TargetingRules;
    expect(updatedRules.logical_operator).toBe('OR');
  });

  it('renders Add Group button at the bottom when there are groups', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={rulesWithOneGroup} onChange={onChange} />);
    // Should have an add-group button even when groups exist
    expect(screen.getByTestId('add-group')).toBeInTheDocument();
  });

  it('shows summary line with group and condition counts', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={rulesWithTwoGroups} onChange={onChange} />);
    // "2 groups, 3 conditions total" or similar
    expect(screen.getByTestId('rules-summary')).toBeInTheDocument();
    expect(screen.getByTestId('rules-summary').textContent).toMatch(/2.*group/i);
    expect(screen.getByTestId('rules-summary').textContent).toMatch(/3.*condition/i);
  });

  it('shows connector label between groups matching logical_operator', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={rulesWithTwoGroups} onChange={onChange} />);
    // Between two groups with OR logical operator, should show OR connector
    expect(screen.getByTestId('group-connector')).toBeInTheDocument();
    expect(screen.getByTestId('group-connector').textContent).toMatch(/OR/i);
  });

  it('renders null value as empty rules', () => {
    const onChange = jest.fn();
    render(<TargetingRuleBuilder value={null} onChange={onChange} />);
    expect(screen.getByText(/No targeting rules.*all users/i)).toBeInTheDocument();
  });

  it('disables all inputs and hides add/remove buttons when readOnly', () => {
    const onChange = jest.fn();
    render(
      <TargetingRuleBuilder value={rulesWithOneGroup} onChange={onChange} readOnly />
    );
    // Should not show add-group button
    expect(screen.queryByTestId('add-group')).not.toBeInTheDocument();
    // Top-level toggles should be disabled
    expect(screen.getByTestId('root-logical-and')).toBeDisabled();
    expect(screen.getByTestId('root-logical-or')).toBeDisabled();
  });
});

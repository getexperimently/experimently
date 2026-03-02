import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { RuleGroupCard } from '@/components/targeting/RuleGroupCard';
import { TargetingRuleGroup } from '@/types/targeting';

const defaultGroup: TargetingRuleGroup = {
  id: 'group-1',
  logical_operator: 'AND',
  conditions: [
    { id: 'cond-1', attribute: 'user.country', operator: 'equals', value: 'US' },
    { id: 'cond-2', attribute: 'user.plan', operator: 'in', value: 'pro' },
  ],
};

const singleConditionGroup: TargetingRuleGroup = {
  id: 'group-2',
  logical_operator: 'OR',
  conditions: [
    { id: 'cond-3', attribute: 'device.type', operator: 'equals', value: 'mobile' },
  ],
};

describe('RuleGroupCard', () => {
  it('renders all conditions in the group', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    // Should render two condition rows
    expect(screen.getAllByTestId('condition-attribute')).toHaveLength(2);
  });

  it('renders group label', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    expect(screen.getByText(/Group 1/i)).toBeInTheDocument();
  });

  it('renders AND/OR toggle buttons', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    expect(screen.getByTestId('group-logical-and')).toBeInTheDocument();
    expect(screen.getByTestId('group-logical-or')).toBeInTheDocument();
  });

  it('calls onChange with updated group when AND is toggled to OR', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    fireEvent.click(screen.getByTestId('group-logical-or'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const updatedGroup = onChange.mock.calls[0][0] as TargetingRuleGroup;
    expect(updatedGroup.logical_operator).toBe('OR');
  });

  it('calls onChange with updated group when OR is toggled to AND', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={singleConditionGroup}
        groupIndex={1}
        isFirst={false}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    fireEvent.click(screen.getByTestId('group-logical-and'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const updatedGroup = onChange.mock.calls[0][0] as TargetingRuleGroup;
    expect(updatedGroup.logical_operator).toBe('AND');
  });

  it('renders "Add Condition" button', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    expect(screen.getByTestId('add-condition')).toBeInTheDocument();
  });

  it('calls onChange with new condition when Add Condition is clicked', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    fireEvent.click(screen.getByTestId('add-condition'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const updatedGroup = onChange.mock.calls[0][0] as TargetingRuleGroup;
    expect(updatedGroup.conditions).toHaveLength(3);
  });

  it('renders remove group button', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    expect(screen.getByTestId('remove-group')).toBeInTheDocument();
  });

  it('calls onRemove when Remove Group button is clicked', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    fireEvent.click(screen.getByTestId('remove-group'));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('hides add/remove buttons when readOnly is true', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
        readOnly
      />
    );
    expect(screen.queryByTestId('add-condition')).not.toBeInTheDocument();
    expect(screen.queryByTestId('remove-group')).not.toBeInTheDocument();
  });

  it('disables AND/OR toggle when readOnly is true', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <RuleGroupCard
        group={defaultGroup}
        groupIndex={0}
        isFirst={true}
        onChange={onChange}
        onRemove={onRemove}
        readOnly
      />
    );
    expect(screen.getByTestId('group-logical-and')).toBeDisabled();
    expect(screen.getByTestId('group-logical-or')).toBeDisabled();
  });
});

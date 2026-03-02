import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConditionRow } from '@/components/targeting/ConditionRow';
import { TargetingCondition } from '@/types/targeting';

const defaultCondition: TargetingCondition = {
  id: 'cond-1',
  attribute: 'user.country',
  operator: 'equals',
  value: 'US',
};

const emptyCondition: TargetingCondition = {
  id: 'cond-2',
  attribute: '',
  operator: 'equals',
  value: '',
};

describe('ConditionRow', () => {
  it('renders attribute input, operator select, and value input', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <ConditionRow
        condition={defaultCondition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    expect(screen.getByTestId('condition-attribute')).toBeInTheDocument();
    expect(screen.getByTestId('condition-operator')).toBeInTheDocument();
    expect(screen.getByTestId('condition-value')).toBeInTheDocument();
  });

  it('renders remove button', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <ConditionRow
        condition={defaultCondition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    expect(screen.getByTestId('condition-remove')).toBeInTheDocument();
  });

  it('calls onRemove when remove button is clicked', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <ConditionRow
        condition={defaultCondition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    fireEvent.click(screen.getByTestId('condition-remove'));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('calls onChange with updated condition when attribute changes', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <ConditionRow
        condition={defaultCondition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    const attributeInput = screen.getByTestId('condition-attribute');
    fireEvent.change(attributeInput, { target: { value: 'user.plan' } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const updated = onChange.mock.calls[0][0] as TargetingCondition;
    expect(updated.attribute).toBe('user.plan');
  });

  it('calls onChange with updated condition when operator changes', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <ConditionRow
        condition={defaultCondition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    const operatorSelect = screen.getByTestId('condition-operator');
    fireEvent.change(operatorSelect, { target: { value: 'contains' } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const updated = onChange.mock.calls[0][0] as TargetingCondition;
    expect(updated.operator).toBe('contains');
  });

  it('calls onChange with updated condition when value changes', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <ConditionRow
        condition={defaultCondition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    const valueInput = screen.getByTestId('condition-value');
    fireEvent.change(valueInput, { target: { value: 'UK' } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const updated = onChange.mock.calls[0][0] as TargetingCondition;
    expect(updated.value).toBe('UK');
  });

  it('hides value input for is_null operator', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    const condition: TargetingCondition = {
      ...defaultCondition,
      operator: 'is_null',
      value: null,
    };
    render(
      <ConditionRow
        condition={condition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    expect(screen.queryByTestId('condition-value')).not.toBeInTheDocument();
  });

  it('hides value input for is_not_null operator', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    const condition: TargetingCondition = {
      ...defaultCondition,
      operator: 'is_not_null',
      value: null,
    };
    render(
      <ConditionRow
        condition={condition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    expect(screen.queryByTestId('condition-value')).not.toBeInTheDocument();
  });

  it('shows comma-hint placeholder for in operator', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    const condition: TargetingCondition = {
      ...defaultCondition,
      operator: 'in',
      value: '',
    };
    render(
      <ConditionRow
        condition={condition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    const valueInput = screen.getByTestId('condition-value');
    expect(valueInput).toHaveAttribute('placeholder', expect.stringContaining(','));
  });

  it('shows comma-hint placeholder for not_in operator', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    const condition: TargetingCondition = {
      ...defaultCondition,
      operator: 'not_in',
      value: '',
    };
    render(
      <ConditionRow
        condition={condition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    const valueInput = screen.getByTestId('condition-value');
    expect(valueInput).toHaveAttribute('placeholder', expect.stringContaining(','));
  });

  it('changes operator options when attribute changes from string to semver', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    // Start with app.version (semver type)
    const semverCondition: TargetingCondition = {
      id: 'cond-s',
      attribute: 'app.version',
      operator: 'semver_eq',
      value: '1.0.0',
    };
    render(
      <ConditionRow
        condition={semverCondition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    const operatorSelect = screen.getByTestId('condition-operator');
    // Should have semver options
    const options = Array.from(operatorSelect.querySelectorAll('option')).map(
      (o) => (o as HTMLOptionElement).value
    );
    expect(options).toContain('semver_eq');
    expect(options).toContain('semver_gt');
    // Should not have string-only options
    expect(options).not.toContain('contains');
  });

  it('shows datalist for attribute autocomplete suggestions', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <ConditionRow
        condition={emptyCondition}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
    // A datalist element should be present for autocomplete
    const datalist = document.querySelector('datalist');
    expect(datalist).toBeInTheDocument();
  });

  it('disables all inputs when readOnly is true', () => {
    const onChange = jest.fn();
    const onRemove = jest.fn();
    render(
      <ConditionRow
        condition={defaultCondition}
        onChange={onChange}
        onRemove={onRemove}
        readOnly
      />
    );
    expect(screen.getByTestId('condition-attribute')).toBeDisabled();
    expect(screen.getByTestId('condition-operator')).toBeDisabled();
    expect(screen.getByTestId('condition-value')).toBeDisabled();
    expect(screen.queryByTestId('condition-remove')).not.toBeInTheDocument();
  });
});

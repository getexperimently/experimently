import { renderHook, act } from '@testing-library/react';
import { useForm } from '@/hooks/useForm';

// A type alias (not an interface) so it satisfies `Record<string, unknown>`;
// interfaces have no implicit index signature.
type TestValues = {
  name: string;
  email: string;
  age: number;
};

const defaults: TestValues = { name: '', email: '', age: 0 };

describe('useForm', () => {
  it('initializes with given values', () => {
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: defaults, onSubmit: jest.fn() }),
    );
    expect(result.current.values).toEqual(defaults);
    expect(result.current.errors).toEqual({});
    expect(result.current.isSubmitting).toBe(false);
    expect(result.current.submitError).toBeNull();
    expect(result.current.isValid).toBe(true);
  });

  it('sets a value', () => {
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: defaults, onSubmit: jest.fn() }),
    );
    act(() => { result.current.setValue('name', 'Alice'); });
    expect(result.current.values.name).toBe('Alice');
  });

  it('validates on change', () => {
    const { result } = renderHook(() =>
      useForm<TestValues>({
        initialValues: defaults,
        validators: {
          name: (v) => (v ? null : 'Required'),
        },
        onSubmit: jest.fn(),
      }),
    );
    act(() => { result.current.setValue('name', ''); });
    expect(result.current.errors.name).toBe('Required');
    expect(result.current.isValid).toBe(false);
  });

  it('clears error when valid', () => {
    const { result } = renderHook(() =>
      useForm<TestValues>({
        initialValues: defaults,
        validators: {
          name: (v) => (v ? null : 'Required'),
        },
        onSubmit: jest.fn(),
      }),
    );
    act(() => { result.current.setValue('name', ''); });
    expect(result.current.errors.name).toBe('Required');
    act(() => { result.current.setValue('name', 'Valid'); });
    expect(result.current.errors.name).toBeUndefined();
    expect(result.current.isValid).toBe(true);
  });

  it('tracks touched fields', () => {
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: defaults, onSubmit: jest.fn() }),
    );
    expect(result.current.touched.name).toBeUndefined();
    act(() => { result.current.setTouched('name'); });
    expect(result.current.touched.name).toBe(true);
  });

  it('calls onSubmit with values when valid', async () => {
    const onSubmit = jest.fn();
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: { ...defaults, name: 'Test' }, onSubmit }),
    );
    await act(async () => { await result.current.handleSubmit(); });
    expect(onSubmit).toHaveBeenCalledWith({ ...defaults, name: 'Test' });
  });

  it('does not call onSubmit when validation fails', async () => {
    const onSubmit = jest.fn();
    const { result } = renderHook(() =>
      useForm<TestValues>({
        initialValues: defaults,
        validators: { name: (v) => (v ? null : 'Required') },
        onSubmit,
      }),
    );
    await act(async () => { await result.current.handleSubmit(); });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(result.current.errors.name).toBe('Required');
  });

  it('marks all fields as touched on submit', async () => {
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: defaults, onSubmit: jest.fn() }),
    );
    await act(async () => { await result.current.handleSubmit(); });
    expect(result.current.touched.name).toBe(true);
    expect(result.current.touched.email).toBe(true);
    expect(result.current.touched.age).toBe(true);
  });

  it('sets submitError on onSubmit failure', async () => {
    const onSubmit = jest.fn().mockRejectedValue(new Error('Server error'));
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: { ...defaults, name: 'X' }, onSubmit }),
    );
    await act(async () => { await result.current.handleSubmit(); });
    expect(result.current.submitError).toBe('Server error');
    expect(result.current.isSubmitting).toBe(false);
  });

  it('sets isSubmitting during async onSubmit', async () => {
    let resolveSubmit: () => void;
    const onSubmit = jest.fn().mockImplementation(
      () => new Promise<void>((resolve) => { resolveSubmit = resolve; }),
    );
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: { ...defaults, name: 'X' }, onSubmit }),
    );

    let submitPromise: Promise<void>;
    act(() => { submitPromise = result.current.handleSubmit(); });
    expect(result.current.isSubmitting).toBe(true);

    await act(async () => {
      resolveSubmit!();
      await submitPromise!;
    });
    expect(result.current.isSubmitting).toBe(false);
  });

  it('resets form state', () => {
    const { result } = renderHook(() =>
      useForm<TestValues>({
        initialValues: defaults,
        validators: { name: (v) => (v ? null : 'Required') },
        onSubmit: jest.fn(),
      }),
    );
    act(() => {
      result.current.setValue('name', 'Alice');
      result.current.setTouched('name');
    });
    act(() => { result.current.reset(); });
    expect(result.current.values).toEqual(defaults);
    expect(result.current.errors).toEqual({});
    expect(result.current.touched).toEqual({});
    expect(result.current.submitError).toBeNull();
  });

  it('prevents default on form event', async () => {
    const onSubmit = jest.fn();
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: { ...defaults, name: 'X' }, onSubmit }),
    );
    const mockEvent = { preventDefault: jest.fn() } as unknown as React.FormEvent;
    await act(async () => { await result.current.handleSubmit(mockEvent); });
    expect(mockEvent.preventDefault).toHaveBeenCalled();
  });

  it('validator receives allValues', () => {
    const validator = jest.fn().mockReturnValue(null);
    const { result } = renderHook(() =>
      useForm<TestValues>({
        initialValues: defaults,
        validators: { name: validator },
        onSubmit: jest.fn(),
      }),
    );
    act(() => { result.current.setValue('name', 'test'); });
    expect(validator).toHaveBeenCalledWith('test', expect.objectContaining({ name: 'test' }));
  });

  it('handles non-Error rejection in onSubmit', async () => {
    const onSubmit = jest.fn().mockRejectedValue('string error');
    const { result } = renderHook(() =>
      useForm<TestValues>({ initialValues: { ...defaults, name: 'X' }, onSubmit }),
    );
    await act(async () => { await result.current.handleSubmit(); });
    expect(result.current.submitError).toBe('string error');
  });
});

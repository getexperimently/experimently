import { useState, useCallback, FormEvent } from 'react';
import { FormErrors } from '@/types/common';

export type Validator<T> = (value: unknown, allValues: T) => string | null;

export interface UseFormOptions<T extends Record<string, unknown>> {
  initialValues: T;
  validators?: Partial<Record<keyof T, Validator<T>>>;
  onSubmit: (values: T) => Promise<void> | void;
}

export interface UseFormResult<T extends Record<string, unknown>> {
  values: T;
  errors: FormErrors<T>;
  touched: Partial<Record<keyof T, boolean>>;
  isSubmitting: boolean;
  submitError: string | null;
  setValue: (field: keyof T, value: T[keyof T]) => void;
  setTouched: (field: keyof T) => void;
  handleSubmit: (e?: FormEvent) => Promise<void>;
  reset: () => void;
  isValid: boolean;
}

export function useForm<T extends Record<string, unknown>>(
  options: UseFormOptions<T>,
): UseFormResult<T> {
  const { initialValues, validators, onSubmit } = options;
  const [values, setValues] = useState<T>(initialValues);
  const [errors, setErrors] = useState<FormErrors<T>>({});
  const [touched, setTouchedState] = useState<Partial<Record<keyof T, boolean>>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const validateField = useCallback(
    (field: keyof T, val: unknown, allVals: T): string | null => {
      const validator = validators?.[field];
      if (!validator) return null;
      return validator(val, allVals);
    },
    [validators],
  );

  const validateAll = useCallback(
    (vals: T): FormErrors<T> => {
      const errs: FormErrors<T> = {};
      if (!validators) return errs;
      for (const field of Object.keys(validators) as Array<keyof T>) {
        const msg = validateField(field, vals[field], vals);
        if (msg) errs[field] = msg;
      }
      return errs;
    },
    [validators, validateField],
  );

  const setValue = useCallback(
    (field: keyof T, value: T[keyof T]) => {
      setValues((prev) => {
        const next = { ...prev, [field]: value };
        const fieldError = validateField(field, value, next);
        setErrors((prevErrors) => {
          const updated = { ...prevErrors };
          if (fieldError) {
            updated[field] = fieldError;
          } else {
            delete updated[field];
          }
          return updated;
        });
        return next;
      });
    },
    [validateField],
  );

  const setTouched = useCallback((field: keyof T) => {
    setTouchedState((prev) => ({ ...prev, [field]: true }));
  }, []);

  const handleSubmit = useCallback(
    async (e?: FormEvent) => {
      if (e) e.preventDefault();
      setSubmitError(null);

      const validationErrors = validateAll(values);
      setErrors(validationErrors);

      // Mark all as touched
      const allTouched: Partial<Record<keyof T, boolean>> = {};
      for (const key of Object.keys(values) as Array<keyof T>) {
        allTouched[key] = true;
      }
      setTouchedState(allTouched);

      if (Object.keys(validationErrors).length > 0) return;

      setIsSubmitting(true);
      try {
        await onSubmit(values);
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsSubmitting(false);
      }
    },
    [values, validateAll, onSubmit],
  );

  const reset = useCallback(() => {
    setValues(initialValues);
    setErrors({});
    setTouchedState({});
    setSubmitError(null);
    setIsSubmitting(false);
  }, [initialValues]);

  const isValid = Object.keys(errors).length === 0;

  return {
    values,
    errors,
    touched,
    isSubmitting,
    submitError,
    setValue,
    setTouched,
    handleSubmit,
    reset,
    isValid,
  };
}

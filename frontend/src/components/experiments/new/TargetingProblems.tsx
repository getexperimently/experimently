import React, { useEffect, useRef } from 'react';
import { CreateError } from './createErrors';

interface TargetingProblemsProps {
  /** A create error carrying `targeting`; anything else renders nothing. */
  error: CreateError | null;
  /** Optional control after the list, e.g. guided setup's "Edit targeting". */
  children?: React.ReactNode;
}

/**
 * Why the targeting rules stopped the create, shown at the targeting rules.
 *
 * An alert, and focus moves to it each time a new error arrives, so a keyboard
 * or screen-reader user lands on the problem rather than on the button they
 * pressed at the foot of the form.
 */
export function TargetingProblems({ error, children }: TargetingProblemsProps) {
  const ref = useRef<HTMLDivElement>(null);
  const problems = error?.targeting;

  useEffect(() => {
    if (problems) ref.current?.focus();
  }, [problems]);

  if (!error || !problems) return null;
  return (
    <div
      ref={ref}
      role="alert"
      tabIndex={-1}
      className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700 focus:outline-none focus:ring-2 focus:ring-blue-600"
      data-testid="targeting-error"
    >
      <p>{error.message}</p>
      <ul className="mt-1 list-disc pl-5">
        {problems.map((problem, i) => (
          <li key={i}>{problem}</li>
        ))}
      </ul>
      {children}
    </div>
  );
}

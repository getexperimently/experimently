import React, { useReducer, useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { ExperimentsService } from '@/services/experiments';
import { PageTitle } from '@/components/PageTitle';
import { AdvancedForm } from '@/components/experiments/new/AdvancedForm';
import {
  buildCreatePayload,
  createInitialFormState,
  experimentFormReducer,
  validateForm,
} from '@/components/experiments/new/formState';

// The form's state, validation and payload live in `formState.ts`; these stay
// importable from the page for the code and tests that already use them.
export { generateKey, validateForm, FORM_EXPERIMENT_TYPES } from '@/components/experiments/new/formState';

export default function NewExperimentPage() {
  const router = useRouter();
  const [state, dispatch] = useReducer(experimentFormReducer, undefined, createInitialFormState);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const problem = validateForm(state.name, state.variants, state.metrics);
    if (problem) {
      setError(problem);
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await ExperimentsService.create(buildCreatePayload(state));
      await router.push(`/experiments/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create experiment');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex-1 bg-slate-50">
      <PageTitle title="New Experiment" />
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link href="/experiments" className="text-slate-500 hover:text-slate-700 text-sm">
            &larr; Experiments
          </Link>
          <h1 className="text-2xl font-bold text-slate-900">New Experiment</h1>
        </div>

        <AdvancedForm
          state={state}
          dispatch={dispatch}
          error={error}
          isSubmitting={isSubmitting}
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  );
}

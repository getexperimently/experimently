import React, { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { PageTitle } from '@/components/PageTitle';

/**
 * `/results` has no index view — results live at `/results/[id]`, reached from
 * an experiment's "View results" button. Send visitors to the experiments list.
 */
export default function ResultsIndexPage() {
  const router = useRouter();

  useEffect(() => {
    void router.replace('/experiments');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex-1 flex items-center justify-center bg-slate-50">
      <PageTitle title="Results" />
      <div className="text-center text-sm text-slate-500" data-testid="results-redirect">
        Redirecting to{' '}
        <Link href="/experiments" className="text-blue-600 hover:underline">
          experiments
        </Link>
        …
      </div>
    </div>
  );
}

import { PageTitle } from '@/components/PageTitle';

export default function ResultsPage() {
  return (
    <div className="flex-1 flex items-center justify-center bg-slate-50">
      <PageTitle title="Results" />
      <div className="text-center">
        <h1 className="text-4xl font-bold text-slate-900 mb-4">Results</h1>
        <p className="text-slate-600">Coming soon - Experiment results</p>
      </div>
    </div>
  );
}

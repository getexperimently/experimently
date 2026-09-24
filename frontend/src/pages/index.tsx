import React, { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useAuth } from '@/contexts/AuthContext';
import { PageTitle } from '@/components/PageTitle';
import { Wordmark } from '@/components/Wordmark';
import { LOGIN_PATH } from '@/services/api';
import { docsUrl } from '@/services/docs';

export const HOME_AFTER_LOGIN = '/experiments';

/**
 * The public homepage.
 *
 * `/` is a `bare` route (see `utils/routes.ts`): no application shell and no
 * `RequireAuth`, so an anonymous visitor sees this page. Every dashboard route
 * is unaffected — `routeKind` returns `protected` for anything not explicitly
 * listed, so authentication is fail-closed by default and this change adds no
 * route to that list.
 *
 * An authenticated visitor is sent straight to the dashboard, which keeps the
 * behaviour anyone already signed in is used to.
 *
 * EVERY CLAIM ON THIS PAGE HAS TO BE TRUE. The landing page that used to live
 * here advertised an event volume, an uptime figure and two compliance
 * certifications for software that has never been deployed, so it could not
 * simply be restored -- `scripts/publish/export.sh` refuses to publish a tree
 * containing those, and `index.test.tsx` asserts the absence of the whole
 * class. (The literals are deliberately not repeated here: this file is swept,
 * and quoting a forbidden claim to explain it trips the gate. That has now
 * happened three times in three different files this week.) What is written
 * below is either checked by a test in this repository or is a statement about
 * the licence and the architecture.
 */
export default function HomePage() {
  const router = useRouter();
  const { status } = useAuth();

  useEffect(() => {
    if (status === 'authenticated') {
      void router.replace(HOME_AFTER_LOGIN);
    }
  }, [status, router]);

  // An authenticated visitor is on their way to the dashboard: render nothing
  // rather than paint the whole marketing page and replace it a moment later.
  // `loading` still renders the page, so an anonymous visitor -- who is every
  // visitor this page exists for -- sees no spinner.
  if (status === 'authenticated') {
    return <PageTitle />;
  }

  return (
    <>
      <PageTitle
        description="Open-source A/B testing and feature flags you run on your own infrastructure. Experiments, targeting rules, frequentist and Bayesian statistics, and fourteen SDKs. Apache-2.0."
      />
      <div data-testid="public-home" className="min-h-screen bg-white text-slate-900">
        <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <Wordmark href={null} />
          <nav className="flex items-center gap-6 text-sm">
            <Link href="/docs" className="text-slate-600 hover:text-slate-900">
              Docs
            </Link>
            <Link href="/power-calculator" className="text-slate-600 hover:text-slate-900">
              Power calculator
            </Link>
            <Link
              href={LOGIN_PATH}
              className="rounded-md bg-blue-600 px-3.5 py-1.5 font-medium text-white hover:bg-blue-700"
            >
              Sign in
            </Link>
          </nav>
        </header>

        <main>
          <section className="mx-auto max-w-5xl px-6 pb-16 pt-10">
            <h1 className="max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
              A/B testing and feature flags you run yourself.
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-relaxed text-slate-600">
              Experimently is an open-source experimentation platform: experiments, feature
              flags, targeting rules and statistics, deployed on your own infrastructure so
              the assignment data never leaves it.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <a
                href={docsUrl('getting-started/quick-start')}
                className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700"
              >
                Get started
              </a>
              <Link
                href={LOGIN_PATH}
                className="rounded-md border border-slate-300 px-4 py-2 font-medium hover:bg-slate-50"
              >
                Sign in to the dashboard
              </Link>
            </div>
            <p className="mt-6 text-sm text-slate-500">
              Apache-2.0. Both build profiles are the same licence and the same price: none.
            </p>
          </section>

          <section className="border-t border-slate-200 bg-slate-50">
            <div className="mx-auto grid max-w-5xl gap-8 px-6 py-14 sm:grid-cols-2 lg:grid-cols-3">
              {[
                {
                  title: 'Experiments and feature flags',
                  body: 'Sticky assignment, gradual rollouts with configurable stages, mutual-exclusion groups and a global holdout, and automated safety rollback on error-rate and latency thresholds.',
                },
                {
                  title: 'Targeting that is actually expressive',
                  body: '20+ operators — semantic version comparison, geo-distance, time windows, JSON path and array operations — compiled and cached, with the throughput floors asserted on every local run.',
                },
                {
                  title: 'Statistics beyond a p-value',
                  body: 'Frequentist and Bayesian analysis, sequential testing with mSPRT for early stopping, CUPED variance reduction, multi-armed bandits, and dimensional breakdowns with multiple-comparison correction.',
                },
                {
                  title: 'SDKs for the stack you have',
                  body: 'JavaScript, React, React Native, Edge, Python, Go, Java, Android, iOS, Ruby, PHP, .NET, Elixir and an OpenFeature provider, all MIT-licensed. Seven of them — JS, Python, Go, Java, Android, React Native and the OpenFeature provider — are pinned to shared golden vectors so their bucketing matches the server byte for byte.',
                },
                {
                  title: 'Runs on your AWS',
                  body: 'A CDK app for ECS Fargate, Aurora PostgreSQL and ElastiCache, or a single docker compose stack on one machine. No hosted tier, so nothing to be locked into.',
                },
                {
                  title: 'Open, and checkable',
                  body: 'The whole platform is Apache-2.0 and the SDKs are MIT. The test suites, the security scans and the release pipeline are in the repository — read them rather than take our word.',
                },
              ].map((card) => (
                <div key={card.title}>
                  <h2 className="text-base font-semibold">{card.title}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">{card.body}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="mx-auto max-w-5xl px-6 py-14">
            <h2 className="text-2xl font-semibold tracking-tight">Run it locally</h2>
            <p className="mt-3 max-w-2xl text-slate-600">
              Four containers — Postgres, Redis, the API and this dashboard — with the
              database created and seeded on the way up.
            </p>
            <pre className="mt-5 overflow-x-auto rounded-lg bg-slate-900 p-5 text-sm leading-relaxed text-slate-100">
              <code>{`git clone https://github.com/getexperimently/experimently.git
cd experimently
docker compose up -d --wait`}</code>
            </pre>
            <p className="mt-4 text-sm text-slate-500">
              Then open <span className="font-mono">localhost:3000</span>. The{' '}
              <a href={docsUrl('getting-started/quick-start')} className="text-blue-700 underline">
                quick start
              </a>{' '}
              has the default credentials and what to change before anyone else can reach it.
            </p>
          </section>
        </main>

        <footer className="border-t border-slate-200">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm text-slate-500">
            <span>Apache-2.0. SDKs MIT.</span>
            <nav className="flex gap-5">
              <Link href="/docs" className="hover:text-slate-900">
                Docs
              </Link>
              <a
                href="https://github.com/getexperimently/experimently"
                className="hover:text-slate-900"
              >
                Source
              </a>
              <Link href={LOGIN_PATH} className="hover:text-slate-900">
                Sign in
              </Link>
            </nav>
          </div>
        </footer>
      </div>
    </>
  );
}

/**
 * The docs hub (`/docs`) makes no claim the repository does not back (T86).
 *
 * Each entry is a claim the hub used to make: an SDK count `sdk/` had
 * outgrown, a latency nobody measured, local hashing the SDKs do not do (the
 * server decides), a one-step deploy that takes several, a search box that was
 * a folder listing, and the AWS name as a hyphenated adjective.
 *
 * The fragments are concatenated, not joined with whitespace, so each entry is
 * exactly the regular expression it reads as once put together; they are split
 * only so the old wording never appears in this file. A bare `\b14\b` is
 * deliberately absent: it matches the hub's correct "iOS 14+".
 *
 * Matched against `container.textContent`, so a claim split across nested
 * elements is still seen. The `<Head>` description is not in it; the
 * marketing build grep covers that.
 */
import React from 'react';
import { render } from '@testing-library/react';
import DocsIndex from '@/pages/docs/index';

jest.mock('next/head', () => { const H=({children}:{children:React.ReactNode})=><>{children}</>; H.displayName='H'; return H; });
jest.mock('next/router', () => ({ useRouter: () => ({ pathname:'/docs', asPath:'/docs', query:{}, push:jest.fn(), replace:jest.fn(), isReady:true }) }));

const retired: Array<[string[], string]> = [
  [['AW', 'S-\\w'], 'the AWS name is not a hyphenated adjective'],
  [['\\b14\\s+', '(languages|SDK)'], 'the SDK count drifted from sdk/'],
  [['Sub-milli', 'second'], 'no latency has been measured'],
  [['consistent\\s+', '(MD5\\s+)?hash'], 'the SDKs do not bucket locally'],
  [['One-', 'command'], 'the CDK deploy takes several steps'],
  [['Search\\s+the', '\\s+documentation'], 'the link opens a listing, not a search'],
];

describe('/docs hub', () => {
  it.each(retired)('no longer says %s (%s)', (parts) => {
    const pattern = new RegExp((parts as string[]).join(''), 'i');
    const { container } = render(<DocsIndex />);
    expect(container.textContent ?? '').not.toMatch(pattern);
  });
});

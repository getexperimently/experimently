/**
 * The dashboard half of the SSO hand-off (C2b spec-v3 §1, §10).
 */
import { ApiError, navigation } from '@/services/api';
import {
  SSO_STORAGE_KEY,
  base64Url,
  codeFromHash,
  emailDomain,
  exchangeFailurePath,
  fromBase64Url,
  handoffHash,
  newSecret,
  readPending,
  readSsoErrorParams,
  ssoErrorMessage,
  startSsoSignIn,
} from '@modules/services/sso';


/**
 * The known-answer vector: the secret is the 32 bytes 00..1f, and HH was
 * computed once with
 *   openssl dgst -sha256 -binary <those bytes> | openssl base64 -A | tr '+/' '-_' | tr -d '='
 * The API's pytest suite pins the same pair.
 */
const SECRET = 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8';
const HH = 'Yw3NKWbEM2aRElRIu7JbT_QSpJxzLbLIq8G4WBvXEN0';

const COPY = { rateLimited: 'RATE-LIMITED-COPY', unreachable: 'UNREACHABLE-COPY' };

describe('the hand-off encoding', () => {
  it('encodes the 32 bytes 00..1f as the spec secret', () => {
    const bytes = new Uint8Array(32).map((_, i) => i);
    expect(base64Url(bytes)).toBe(SECRET);
    expect(Array.from(fromBase64Url(SECRET))).toEqual(Array.from(bytes));
  });

  it('hashes the decoded bytes, not the text: the known-answer vector', async () => {
    await expect(handoffHash(SECRET)).resolves.toBe(HH);
  });

  it('makes a 43-character base64url secret of 32 random bytes', () => {
    const a = newSecret();
    const b = newSecret();
    expect(a).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(fromBase64Url(a)).toHaveLength(32);
    expect(a).not.toBe(b);
  });
});

describe('codeFromHash', () => {
  it('accepts only #code=<JWT-shaped> of at most 2048 characters', () => {
    expect(codeFromHash('#code=a.b.c')).toBe('a.b.c');
    expect(codeFromHash(`#code=${'a'.repeat(2044)}.b.c`)).toHaveLength(2048);
    expect(codeFromHash(`#code=${'a'.repeat(2045)}.b.c`)).toBeNull();
    for (const bad of ['', '#', '#code=', '#code=a.b', '#code=a.b.c&x=1', '#token=a.b.c', '#code=a.b.c%20']) {
      expect(codeFromHash(bad)).toBeNull();
    }
  });
});

describe('emailDomain', () => {
  it('is the lower-cased domain of a work email, or null', () => {
    expect(emailDomain('  Me@Acme.COM ')).toBe('acme.com');
    expect(emailDomain('acme.com')).toBeNull();
    expect(emailDomain('me@localhost')).toBeNull();
    expect(emailDomain('me@ex ample.com')).toBeNull();
  });
});

describe('startSsoSignIn', () => {
  beforeEach(() => window.sessionStorage.clear());

  it('keeps the secret in sessionStorage and navigates with its hash, never the secret', async () => {
    const assign = jest.spyOn(navigation, 'assign').mockImplementation(() => undefined);
    await startSsoSignIn('me@Acme.com', '/feature-flags');
    const pending = readPending();
    expect(pending).not.toBeNull();
    expect(pending?.next).toBe('/feature-flags');
    expect(pending?.domain).toBe('acme.com');

    expect(assign).toHaveBeenCalledTimes(1);
    const url = new URL(assign.mock.calls[0][0], 'http://localhost');
    expect(url.pathname).toBe('/api/v1/auth/sso/login');
    expect(url.searchParams.get('domain')).toBe('acme.com');
    expect(url.searchParams.get('return_to')).toBe(window.location.origin);
    expect(url.searchParams.get('handoff')).toBe(await handoffHash(pending!.secret));
    expect(assign.mock.calls[0][0]).not.toContain(pending!.secret);
    expect(assign.mock.calls[0][0]).not.toContain('me%40');
    assign.mockRestore();
  });

  it('refuses an address with no usable domain and navigates nowhere', async () => {
    const assign = jest.spyOn(navigation, 'assign').mockImplementation(() => undefined);
    await expect(startSsoSignIn('not-an-email', '/')).rejects.toThrow(/work email/);
    expect(assign).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(SSO_STORAGE_KEY)).toBeNull();
    assign.mockRestore();
  });
});

describe('exchangeFailurePath', () => {
  it('maps each failure to its /login?sso_error', () => {
    expect(exchangeFailurePath(new ApiError({ status: 400 }))).toBe('/login?sso_error=sso_state');
    expect(exchangeFailurePath(new ApiError({ status: 429 }))).toBe('/login?sso_error=sso_rate_limited');
    expect(exchangeFailurePath(new ApiError({ status: 0 }))).toBe('/login?sso_error=sso_unreachable');
    expect(exchangeFailurePath(new ApiError({ status: 502, requestId: 'req-1' }))).toBe(
      '/login?sso_error=sso_failed&request_id=req-1',
    );
    expect(exchangeFailurePath(new ApiError({ status: 500 }))).toBe('/login?sso_error=sso_failed');
  });
});

describe('readSsoErrorParams', () => {
  it('keeps only values shaped the way the API writes them', () => {
    expect(
      readSsoErrorParams({
        sso_error: 'sso_idp_error',
        provider: 'okta',
        idp_error: 'access_denied',
        request_id: 'abc-123',
      }),
    ).toEqual({ sso_error: 'sso_idp_error', provider: 'okta', idp_error: 'access_denied', request_id: 'abc-123' });
    expect(
      readSsoErrorParams({
        sso_error: 'sso_idp_error',
        provider: 'evil',
        idp_error: 'Visit evil.example',
        request_id: '<b>',
      }),
    ).toEqual({ sso_error: 'sso_idp_error' });
    expect(readSsoErrorParams({ sso_error: '<script>' })).toEqual({ sso_error: 'unknown' });
    expect(readSsoErrorParams({})).toBeNull();
  });
});

describe('ssoErrorMessage: the copy for every code (spec-v3 §10)', () => {
  const host = window.location.host;
  const cases: Array<[Record<string, string>, string, string?]> = [
    [{ sso_error: 'sso_expired' }, 'Your sign-in took too long and expired. Start again.'],
    [
      { sso_error: 'sso_state' },
      "We couldn't confirm this sign-in was started in this browser. Start again from this page. " +
        `If it keeps happening, make sure cookies are allowed for ${host}.`,
    ],
    [
      { sso_error: 'sso_idp_error', provider: 'okta', idp_error: 'access_denied' },
      'Okta did not complete the sign-in (access_denied). If you expected access, contact your administrator.',
    ],
    [
      { sso_error: 'sso_email', provider: 'google' },
      'Google did not send a usable email address for your account. Ask your administrator.',
    ],
    [
      { sso_error: 'sso_unverified', provider: 'github' },
      'GitHub has not verified the email address on your account. Verify it with GitHub, or ask your administrator.',
    ],
    [
      { sso_error: 'sso_domain', provider: 'okta' },
      "Okta signed you in with an account outside this organisation's domain. Use your work account, or ask your administrator.",
    ],
    [
      { sso_error: 'sso_account', request_id: 'req-9' },
      "Your account needs an administrator's attention before you can sign in. Give them this Request ID: req-9.",
    ],
    [{ sso_error: 'sso_inactive' }, 'Your account is deactivated. Ask your administrator.'],
    [
      { sso_error: 'sso_not_configured' },
      "Single sign-on isn't set up for acme.com. Sign in with your password, or ask your administrator.",
      'acme.com',
    ],
    [
      { sso_error: 'sso_saml_only' },
      "acme.com signs in through your identity provider's portal. Start from there, or ask your administrator.",
      'acme.com',
    ],
    [
      { sso_error: 'sso_failed', provider: 'okta', request_id: 'req-7' },
      'Sign-in with Okta failed. Your administrator can find the details in the API log (Request ID: req-7).',
    ],
    [
      { sso_error: 'sso_failed', provider: 'okta' },
      'Sign-in with Okta failed. Your administrator can find the details in the API log.',
    ],
    [{ sso_error: 'sso_rate_limited' }, 'RATE-LIMITED-COPY'],
    [{ sso_error: 'sso_unreachable' }, 'UNREACHABLE-COPY'],
    [{ sso_error: 'something_new' }, "Sign-in didn't complete. Start again."],
  ];

  // Every row padded to three entries: jest reads a callback parameter that
  // a row leaves out as the test's `done`.
  const rows = cases.map(([query, expected, domain]) => [query, expected, domain ?? ''] as const);
  it.each(rows)('%j', (query, expected, domain) => {
    const params = readSsoErrorParams(query);
    expect(params).not.toBeNull();
    expect(ssoErrorMessage(params!, { ...COPY, domain: domain || undefined })).toBe(expected);
  });

  it('never shows an idp_error that is not an OAuth code', () => {
    const params = readSsoErrorParams({ sso_error: 'sso_idp_error', idp_error: 'Call +1 555 0100' })!;
    expect(ssoErrorMessage(params, COPY)).toBe(
      'Your identity provider did not complete the sign-in. If you expected access, contact your administrator.',
    );
  });
});

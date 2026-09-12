/**
 * Shared scaffolding for page tests: a routed `apiFetch` mock, a `next/router`
 * stub and the `next/head` passthrough. Each test file still declares the
 * `jest.mock(...)` calls itself (jest hoists them per file); this module only
 * provides the implementations.
 */
import React from 'react';
import { ApiError, ApiFetchOptions } from '@/services/api';

export type Handler = (path: string, options: ApiFetchOptions) => unknown | Promise<unknown>;

export interface Route {
  method?: string;
  /** Exact path (query string stripped) or a RegExp. */
  path: string | RegExp;
  handler: Handler;
}

export function apiError(status: number, detail: string): ApiError {
  return new ApiError({ status, detail });
}

/** Build an `apiFetch` implementation that dispatches on method + path. */
export function routedApi(routes: Route[]) {
  return jest.fn(async (rawPath: string, options: ApiFetchOptions = {}) => {
    const method = (options.method ?? 'GET').toUpperCase();
    const path = rawPath.split('?')[0];
    const route = routes.find((r) => {
      const methodOk = (r.method ?? 'GET').toUpperCase() === method;
      const pathOk = typeof r.path === 'string' ? r.path === path : r.path.test(path);
      return methodOk && pathOk;
    });
    if (!route) {
      throw apiError(404, `No mock route for ${method} ${path}`);
    }
    return route.handler(rawPath, options);
  });
}

export function MockHead({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
MockHead.displayName = 'MockHead';

export function makeRouter(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    push: jest.fn().mockResolvedValue(true),
    replace: jest.fn().mockResolvedValue(true),
    prefetch: jest.fn().mockResolvedValue(undefined),
    back: jest.fn(),
    pathname: '/',
    asPath: '/',
    query: {},
    isReady: true,
    events: { on: jest.fn(), off: jest.fn(), emit: jest.fn() },
    ...overrides,
  };
}

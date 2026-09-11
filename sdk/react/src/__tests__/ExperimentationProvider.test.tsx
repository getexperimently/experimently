import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, renderHook } from '@testing-library/react';
import {
  ExperimentationProvider,
  useExperimentation,
  useExperimentationContext,
} from '../context/ExperimentationProvider';
import { ExperimentationClient } from '../client/ExperimentationClient';
import { SdkConfig, UserContext } from '../client/types';

const config: SdkConfig = {
  apiKey: 'test-key',
  baseUrl: 'https://api.example.com',
};

const user: UserContext = { userId: 'user-1' };

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <ExperimentationProvider config={config} user={user}>
      {children}
    </ExperimentationProvider>
  );
}

describe('ExperimentationProvider', () => {
  it('renders children without error', () => {
    render(
      <ExperimentationProvider config={config} user={user}>
        <span data-testid="child">hello</span>
      </ExperimentationProvider>
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  it('provides a client instance to children via useExperimentation', () => {
    const { result } = renderHook(() => useExperimentation(), { wrapper });
    expect(result.current.client).toBeInstanceOf(ExperimentationClient);
  });

  it('provides the user object to children via useExperimentation', () => {
    const { result } = renderHook(() => useExperimentation(), { wrapper });
    expect(result.current.user.userId).toBe('user-1');
  });

  it('exposes useExperimentationContext as an alias of useExperimentation', () => {
    expect(useExperimentationContext).toBe(useExperimentation);
    const { result } = renderHook(() => useExperimentationContext(), { wrapper });
    expect(result.current.client).toBeInstanceOf(ExperimentationClient);
    expect(result.current.user.userId).toBe('user-1');
  });

  it('throws when useExperimentation is used outside the provider', () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(() => renderHook(() => useExperimentation())).toThrow(
      'useExperimentation must be used within ExperimentationProvider'
    );

    consoleError.mockRestore();
  });

  it('throws when useExperimentationContext is used outside the provider', () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(() => renderHook(() => useExperimentationContext())).toThrow(
      /must be used within ExperimentationProvider/
    );

    consoleError.mockRestore();
  });

  it('provides the same client instance across re-renders (stable reference)', () => {
    const { result, rerender } = renderHook(() => useExperimentation(), { wrapper });
    const firstClient = result.current.client;
    rerender();
    expect(result.current.client).toBe(firstClient);
  });

  it('keeps the same client when an equivalent config object is passed on re-render', () => {
    const DynamicWrapper = ({ children }: { children: React.ReactNode }) => (
      <ExperimentationProvider config={{ ...config }} user={user}>
        {children}
      </ExperimentationProvider>
    );
    const { result, rerender } = renderHook(() => useExperimentation(), { wrapper: DynamicWrapper });
    const firstClient = result.current.client;
    rerender();
    expect(result.current.client).toBe(firstClient);
  });

  it('creates a new client when apiKey changes', () => {
    let currentConfig = config;
    const DynamicWrapper = ({ children }: { children: React.ReactNode }) => (
      <ExperimentationProvider config={currentConfig} user={user}>
        {children}
      </ExperimentationProvider>
    );

    const { result, rerender } = renderHook(() => useExperimentation(), { wrapper: DynamicWrapper });
    const firstClient = result.current.client;

    currentConfig = { ...config, apiKey: 'different-key' };
    rerender();
    expect(result.current.client).not.toBe(firstClient);
  });

  it('reflects updated user.userId in context when user prop changes', () => {
    let currentUser = user;
    const DynamicWrapper = ({ children }: { children: React.ReactNode }) => (
      <ExperimentationProvider config={config} user={currentUser}>
        {children}
      </ExperimentationProvider>
    );

    const { result, rerender } = renderHook(() => useExperimentation(), { wrapper: DynamicWrapper });
    expect(result.current.user.userId).toBe('user-1');

    currentUser = { userId: 'user-2' };
    rerender();
    expect(result.current.user.userId).toBe('user-2');
  });

  it('keeps a stable user reference when an equivalent user object is passed on re-render', () => {
    const DynamicWrapper = ({ children }: { children: React.ReactNode }) => (
      <ExperimentationProvider config={config} user={{ userId: 'user-1', attributes: { device: 'mobile' } }}>
        {children}
      </ExperimentationProvider>
    );
    const { result, rerender } = renderHook(() => useExperimentation(), { wrapper: DynamicWrapper });
    const firstUser = result.current.user;
    rerender();
    expect(result.current.user).toBe(firstUser);
  });

  it('updates the user reference when attributes change', () => {
    let currentUser: UserContext = { userId: 'user-1', attributes: { device: 'mobile' } };
    const DynamicWrapper = ({ children }: { children: React.ReactNode }) => (
      <ExperimentationProvider config={config} user={currentUser}>
        {children}
      </ExperimentationProvider>
    );
    const { result, rerender } = renderHook(() => useExperimentation(), { wrapper: DynamicWrapper });
    const firstUser = result.current.user;

    currentUser = { userId: 'user-1', attributes: { device: 'desktop' } };
    rerender();
    expect(result.current.user).not.toBe(firstUser);
    expect(result.current.user.attributes).toEqual({ device: 'desktop' });
  });
});

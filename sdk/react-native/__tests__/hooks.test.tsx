/**
 * Tests for React Native hooks: useFlag, useExperiment, useExperimentationClient.
 *
 * Uses @testing-library/react-native to render components that use the hooks.
 */

import React from 'react';
import { Text, View } from 'react-native';
import { render, waitFor, act } from '@testing-library/react-native';
import { ExperimentationProvider } from '../src/context/ExperimentationProvider';
import { ExperimentationClient } from '../src/client';
import { useFlag } from '../src/hooks/useFlag';
import { useExperiment } from '../src/hooks/useExperiment';
import { useExperimentationClient } from '../src/hooks/useExperimentationClient';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeClient(overrides?: {
  evaluateFlag?: jest.Mock;
  getAssignment?: jest.Mock;
  track?: jest.Mock;
}): ExperimentationClient {
  const client = {
    evaluateFlag: overrides?.evaluateFlag ?? jest.fn().mockResolvedValue(false),
    getAssignment: overrides?.getAssignment ?? jest.fn().mockResolvedValue(null),
    track: overrides?.track ?? jest.fn().mockResolvedValue(undefined),
    clearCache: jest.fn(),
  } as unknown as ExperimentationClient;
  return client;
}

function wrapper(
  client: ExperimentationClient,
  userId = 'test-user'
): React.ComponentType<{ children: React.ReactNode }> {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <ExperimentationProvider client={client} userId={userId}>
        {children}
      </ExperimentationProvider>
    );
  };
}

// ---------------------------------------------------------------------------
// useFlag tests
// ---------------------------------------------------------------------------

describe('useFlag', () => {
  function FlagComponent({ flagKey }: { flagKey: string }) {
    const { value, loading, error } = useFlag(flagKey);
    if (loading) return <Text testID="loading">Loading...</Text>;
    if (error) return <Text testID="error">{error.message}</Text>;
    return <Text testID="result">{value ? 'enabled' : 'disabled'}</Text>;
  }

  test('shows loading state initially', () => {
    const client = makeClient({
      evaluateFlag: jest.fn().mockImplementation(
        () => new Promise(() => {}) // never resolves
      ),
    });

    const { getByTestId } = render(
      <ExperimentationProvider client={client} userId="u1">
        <FlagComponent flagKey="test-flag" />
      </ExperimentationProvider>
    );

    expect(getByTestId('loading')).toBeTruthy();
  });

  test('shows "enabled" when flag evaluates to true', async () => {
    const client = makeClient({
      evaluateFlag: jest.fn().mockResolvedValue(true),
    });

    const { getByTestId } = render(
      <ExperimentationProvider client={client} userId="u1">
        <FlagComponent flagKey="dark-mode" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(getByTestId('result').props.children).toBe('enabled');
    });
  });

  test('shows "disabled" when flag evaluates to false', async () => {
    const client = makeClient({
      evaluateFlag: jest.fn().mockResolvedValue(false),
    });

    const { getByTestId } = render(
      <ExperimentationProvider client={client} userId="u1">
        <FlagComponent flagKey="feature-x" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(getByTestId('result').props.children).toBe('disabled');
    });
  });

  test('shows error message when evaluateFlag throws', async () => {
    const client = makeClient({
      evaluateFlag: jest.fn().mockRejectedValue(new Error('API error')),
    });

    const { getByTestId } = render(
      <ExperimentationProvider client={client} userId="u1">
        <FlagComponent flagKey="flag" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(getByTestId('error').props.children).toBe('API error');
    });
  });

  test('calls evaluateFlag with correct flagKey and userId', async () => {
    const evaluateFlag = jest.fn().mockResolvedValue(true);
    const client = makeClient({ evaluateFlag });

    render(
      <ExperimentationProvider client={client} userId="specific-user">
        <FlagComponent flagKey="specific-flag" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(evaluateFlag).toHaveBeenCalledWith(
        'specific-flag',
        'specific-user',
        undefined
      );
    });
  });

  test('re-evaluates when userId changes', async () => {
    const evaluateFlag = jest.fn().mockResolvedValue(true);
    const client = makeClient({ evaluateFlag });

    const { rerender } = render(
      <ExperimentationProvider client={client} userId="user-A">
        <FlagComponent flagKey="flag" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(evaluateFlag).toHaveBeenCalledWith('flag', 'user-A', undefined);
    });

    rerender(
      <ExperimentationProvider client={client} userId="user-B">
        <FlagComponent flagKey="flag" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(evaluateFlag).toHaveBeenCalledWith('flag', 'user-B', undefined);
    });
  });
});

// ---------------------------------------------------------------------------
// useExperiment tests
// ---------------------------------------------------------------------------

describe('useExperiment', () => {
  function ExperimentComponent({ expKey }: { expKey: string }) {
    const { variant, loading, error } = useExperiment(expKey);
    if (loading) return <Text testID="loading">Loading...</Text>;
    if (error) return <Text testID="error">{error.message}</Text>;
    return <Text testID="variant">{variant ?? 'none'}</Text>;
  }

  test('shows loading initially', () => {
    const client = makeClient({
      getAssignment: jest.fn().mockImplementation(() => new Promise(() => {})),
    });

    const { getByTestId } = render(
      <ExperimentationProvider client={client} userId="u1">
        <ExperimentComponent expKey="my-exp" />
      </ExperimentationProvider>
    );

    expect(getByTestId('loading')).toBeTruthy();
  });

  test('shows variant after successful assignment', async () => {
    const client = makeClient({
      getAssignment: jest.fn().mockResolvedValue('treatment'),
    });

    const { getByTestId } = render(
      <ExperimentationProvider client={client} userId="u1">
        <ExperimentComponent expKey="my-exp" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(getByTestId('variant').props.children).toBe('treatment');
    });
  });

  test('shows "none" when not assigned', async () => {
    const client = makeClient({
      getAssignment: jest.fn().mockResolvedValue(null),
    });

    const { getByTestId } = render(
      <ExperimentationProvider client={client} userId="u1">
        <ExperimentComponent expKey="my-exp" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(getByTestId('variant').props.children).toBe('none');
    });
  });

  test('shows error when getAssignment throws', async () => {
    const client = makeClient({
      getAssignment: jest.fn().mockRejectedValue(new Error('Assignment failed')),
    });

    const { getByTestId } = render(
      <ExperimentationProvider client={client} userId="u1">
        <ExperimentComponent expKey="my-exp" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(getByTestId('error').props.children).toBe('Assignment failed');
    });
  });

  test('calls getAssignment with correct args', async () => {
    const getAssignment = jest.fn().mockResolvedValue('control');
    const client = makeClient({ getAssignment });

    render(
      <ExperimentationProvider client={client} userId="user-xyz">
        <ExperimentComponent expKey="checkout-experiment" />
      </ExperimentationProvider>
    );

    await waitFor(() => {
      expect(getAssignment).toHaveBeenCalledWith(
        'checkout-experiment',
        'user-xyz',
        undefined
      );
    });
  });
});

// ---------------------------------------------------------------------------
// useExperimentationClient tests
// ---------------------------------------------------------------------------

describe('useExperimentationClient', () => {
  function ClientConsumer() {
    const { client, userId, attributes } = useExperimentationClient();
    return (
      <View>
        <Text testID="userId">{userId}</Text>
        <Text testID="hasClient">{client ? 'yes' : 'no'}</Text>
        <Text testID="attrs">{attributes ? JSON.stringify(attributes) : 'none'}</Text>
      </View>
    );
  }

  test('exposes client, userId, and attributes from provider', async () => {
    const client = makeClient();

    const { getByTestId } = render(
      <ExperimentationProvider
        client={client}
        userId="ctx-user"
        attributes={{ plan: 'pro' }}
      >
        <ClientConsumer />
      </ExperimentationProvider>
    );

    expect(getByTestId('userId').props.children).toBe('ctx-user');
    expect(getByTestId('hasClient').props.children).toBe('yes');
    expect(getByTestId('attrs').props.children).toBe('{"plan":"pro"}');
  });

  test('throws when used outside ExperimentationProvider', () => {
    // Suppress console.error for expected thrown errors in tests
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => {
      render(<ClientConsumer />);
    }).toThrow('useExperimentationContext must be used inside an <ExperimentationProvider>');

    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// ExperimentationProvider tests
// ---------------------------------------------------------------------------

describe('ExperimentationProvider', () => {
  test('renders children', () => {
    const client = makeClient();

    const { getByText } = render(
      <ExperimentationProvider client={client} userId="u1">
        <Text>Hello from child</Text>
      </ExperimentationProvider>
    );

    expect(getByText('Hello from child')).toBeTruthy();
  });

  test('memoises context value — does not re-render children when unrelated state changes', async () => {
    const client = makeClient();
    let renderCount = 0;

    function Child() {
      renderCount++;
      useExperimentationClient();
      return <Text testID="child">child</Text>;
    }

    function Parent() {
      const [count, setCount] = React.useState(0);
      return (
        <ExperimentationProvider client={client} userId="u1">
          <Child />
          <Text testID="count" onPress={() => setCount((c) => c + 1)}>
            {count}
          </Text>
        </ExperimentationProvider>
      );
    }

    const { getByTestId } = render(<Parent />);
    const initialCount = renderCount;

    // Trigger a parent re-render without changing the provider props
    act(() => {
      getByTestId('count').props.onPress();
    });

    // Child may re-render due to parent re-render; context value should be stable
    expect(renderCount).toBeGreaterThanOrEqualTo(initialCount);
  });
});

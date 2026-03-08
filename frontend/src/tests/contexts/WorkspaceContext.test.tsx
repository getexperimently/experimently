import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { WorkspaceProvider, useWorkspace } from '@/contexts/WorkspaceContext';

function TestConsumer() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  return (
    <div>
      <span data-testid="ws">{workspaceId ?? 'none'}</span>
      <button onClick={() => setWorkspaceId('ws-1')}>set</button>
      <button onClick={() => setWorkspaceId(null)}>clear</button>
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe('WorkspaceContext', () => {
  it('throws when used outside provider', () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow('useWorkspace must be used within WorkspaceProvider');
    spy.mockRestore();
  });

  it('starts with null when localStorage is empty', () => {
    render(<WorkspaceProvider><TestConsumer /></WorkspaceProvider>);
    expect(screen.getByTestId('ws').textContent).toBe('none');
  });

  it('hydrates from localStorage', () => {
    localStorage.setItem('current_workspace', 'ws-stored');
    render(<WorkspaceProvider><TestConsumer /></WorkspaceProvider>);
    expect(screen.getByTestId('ws').textContent).toBe('ws-stored');
  });

  it('sets workspace and persists', () => {
    render(<WorkspaceProvider><TestConsumer /></WorkspaceProvider>);
    act(() => { screen.getByText('set').click(); });
    expect(screen.getByTestId('ws').textContent).toBe('ws-1');
    expect(localStorage.getItem('current_workspace')).toBe('ws-1');
  });

  it('clears workspace', () => {
    localStorage.setItem('current_workspace', 'ws-1');
    render(<WorkspaceProvider><TestConsumer /></WorkspaceProvider>);
    act(() => { screen.getByText('clear').click(); });
    expect(screen.getByTestId('ws').textContent).toBe('none');
    expect(localStorage.getItem('current_workspace')).toBeNull();
  });
});

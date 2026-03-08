import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { AuthUser } from '@/types/common';

const mockUser: AuthUser = {
  id: '1',
  username: 'testuser',
  email: 'test@example.com',
  role: 'ADMIN',
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
};

function TestConsumer() {
  const { user, isAuthenticated, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="authed">{String(isAuthenticated)}</span>
      <span data-testid="username">{user?.username ?? 'none'}</span>
      <button onClick={() => login(mockUser)}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe('AuthContext', () => {
  it('throws when used outside provider', () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow('useAuth must be used within AuthProvider');
    spy.mockRestore();
  });

  it('starts unauthenticated when localStorage is empty', () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>);
    expect(screen.getByTestId('authed').textContent).toBe('false');
    expect(screen.getByTestId('username').textContent).toBe('none');
  });

  it('hydrates from localStorage on mount', () => {
    localStorage.setItem('admin_user', JSON.stringify(mockUser));
    render(<AuthProvider><TestConsumer /></AuthProvider>);
    expect(screen.getByTestId('authed').textContent).toBe('true');
    expect(screen.getByTestId('username').textContent).toBe('testuser');
  });

  it('handles corrupted localStorage gracefully', () => {
    localStorage.setItem('admin_user', 'not-json');
    render(<AuthProvider><TestConsumer /></AuthProvider>);
    expect(screen.getByTestId('authed').textContent).toBe('false');
  });

  it('login sets user and persists to localStorage', () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>);
    act(() => { screen.getByText('login').click(); });
    expect(screen.getByTestId('authed').textContent).toBe('true');
    expect(screen.getByTestId('username').textContent).toBe('testuser');
    expect(localStorage.getItem('admin_user')).toBeTruthy();
  });

  it('logout clears user and localStorage', () => {
    localStorage.setItem('admin_user', JSON.stringify(mockUser));
    render(<AuthProvider><TestConsumer /></AuthProvider>);
    act(() => { screen.getByText('logout').click(); });
    expect(screen.getByTestId('authed').textContent).toBe('false');
    expect(localStorage.getItem('admin_user')).toBeNull();
  });

  it('login then logout round-trips correctly', () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>);
    act(() => { screen.getByText('login').click(); });
    expect(screen.getByTestId('authed').textContent).toBe('true');
    act(() => { screen.getByText('logout').click(); });
    expect(screen.getByTestId('authed').textContent).toBe('false');
  });
});

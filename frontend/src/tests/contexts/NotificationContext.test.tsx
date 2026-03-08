import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { NotificationProvider, useNotifications } from '@/contexts/NotificationContext';

function TestConsumer() {
  const { toasts, addToast, removeToast } = useNotifications();
  return (
    <div>
      <span data-testid="count">{toasts.length}</span>
      {toasts.map((t) => (
        <span key={t.id} data-testid={`toast-${t.id}`}>
          {t.variant}:{t.message}
        </span>
      ))}
      <button onClick={() => addToast('hello', 'success', 0)}>add</button>
      <button onClick={() => addToast('auto', 'info', 100)}>add-auto</button>
      <button onClick={() => { if (toasts[0]) removeToast(toasts[0].id); }}>remove</button>
    </div>
  );
}

describe('NotificationContext', () => {
  it('throws when used outside provider', () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow('useNotifications must be used within NotificationProvider');
    spy.mockRestore();
  });

  it('starts with no toasts', () => {
    render(<NotificationProvider><TestConsumer /></NotificationProvider>);
    expect(screen.getByTestId('count').textContent).toBe('0');
  });

  it('adds a toast', () => {
    render(<NotificationProvider><TestConsumer /></NotificationProvider>);
    act(() => { screen.getByText('add').click(); });
    expect(screen.getByTestId('count').textContent).toBe('1');
  });

  it('removes a toast manually', () => {
    render(<NotificationProvider><TestConsumer /></NotificationProvider>);
    act(() => { screen.getByText('add').click(); });
    expect(screen.getByTestId('count').textContent).toBe('1');
    act(() => { screen.getByText('remove').click(); });
    expect(screen.getByTestId('count').textContent).toBe('0');
  });

  it('auto-dismisses after duration', () => {
    jest.useFakeTimers();
    render(<NotificationProvider><TestConsumer /></NotificationProvider>);
    act(() => { screen.getByText('add-auto').click(); });
    expect(screen.getByTestId('count').textContent).toBe('1');
    act(() => { jest.advanceTimersByTime(150); });
    expect(screen.getByTestId('count').textContent).toBe('0');
    jest.useRealTimers();
  });

  it('renders correct variant', () => {
    render(<NotificationProvider><TestConsumer /></NotificationProvider>);
    act(() => { screen.getByText('add').click(); });
    expect(screen.getByTestId('count').textContent).toBe('1');
    const toast = screen.getAllByText(/success:hello/);
    expect(toast.length).toBe(1);
  });
});

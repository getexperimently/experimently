import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { NotificationProvider, useNotifications } from '@/contexts/NotificationContext';
import { ToastContainer } from '@/components/ToastContainer';

function Trigger() {
  const { addToast } = useNotifications();
  return (
    <>
      <button onClick={() => addToast('Success!', 'success', 0)}>add-success</button>
      <button onClick={() => addToast('Error!', 'error', 0)}>add-error</button>
      <button onClick={() => addToast('Warning!', 'warning', 0)}>add-warning</button>
      <button onClick={() => addToast('Info!', 'info', 0)}>add-info</button>
    </>
  );
}

function Wrapper() {
  return (
    <NotificationProvider>
      <Trigger />
      <ToastContainer />
    </NotificationProvider>
  );
}

describe('ToastContainer', () => {
  it('renders nothing when no toasts', () => {
    render(<Wrapper />);
    expect(screen.queryByTestId('toast-container')).not.toBeInTheDocument();
  });

  it('renders a success toast', () => {
    render(<Wrapper />);
    act(() => { screen.getByText('add-success').click(); });
    expect(screen.getByTestId('toast-container')).toBeInTheDocument();
    expect(screen.getByText('Success!')).toBeInTheDocument();
  });

  it('renders multiple toasts', () => {
    render(<Wrapper />);
    act(() => {
      screen.getByText('add-success').click();
      screen.getByText('add-error').click();
    });
    expect(screen.getByText('Success!')).toBeInTheDocument();
    expect(screen.getByText('Error!')).toBeInTheDocument();
  });

  it('dismisses a toast on click', () => {
    render(<Wrapper />);
    act(() => { screen.getByText('add-info').click(); });
    const dismissBtns = screen.getAllByLabelText('Dismiss');
    act(() => { dismissBtns[0].click(); });
    expect(screen.queryByText('Info!')).not.toBeInTheDocument();
  });

  it('has aria-live for accessibility', () => {
    render(<Wrapper />);
    act(() => { screen.getByText('add-info').click(); });
    expect(screen.getByTestId('toast-container')).toHaveAttribute('aria-live', 'polite');
  });

  it('renders all four variants', () => {
    render(<Wrapper />);
    act(() => {
      screen.getByText('add-success').click();
      screen.getByText('add-error').click();
      screen.getByText('add-warning').click();
      screen.getByText('add-info').click();
    });
    expect(screen.getByText('Success!')).toBeInTheDocument();
    expect(screen.getByText('Error!')).toBeInTheDocument();
    expect(screen.getByText('Warning!')).toBeInTheDocument();
    expect(screen.getByText('Info!')).toBeInTheDocument();
  });
});

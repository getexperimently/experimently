import React from 'react';
import { useNotifications } from '@/contexts/NotificationContext';
import { ToastVariant } from '@/types/common';

const VARIANT_STYLES: Record<ToastVariant, string> = {
  success: 'bg-green-50 border-green-300 text-green-800',
  error: 'bg-red-50 border-red-300 text-red-800',
  warning: 'bg-yellow-50 border-yellow-300 text-yellow-800',
  info: 'bg-blue-50 border-blue-300 text-blue-800',
};

export function ToastContainer() {
  const { toasts, removeToast } = useNotifications();

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      data-testid="toast-container"
      className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          data-testid={`toast-${toast.id}`}
          className={`flex items-start gap-2 px-4 py-3 rounded-lg border text-sm shadow-md animate-slide-in ${VARIANT_STYLES[toast.variant]}`}
        >
          <span className="flex-1">{toast.message}</span>
          <button
            onClick={() => removeToast(toast.id)}
            data-testid={`toast-dismiss-${toast.id}`}
            className="shrink-0 opacity-60 hover:opacity-100 transition-opacity text-current"
            aria-label="Dismiss"
          >
            &times;
          </button>
        </div>
      ))}
    </div>
  );
}

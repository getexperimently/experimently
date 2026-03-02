import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { AdminUser, UserRole } from '@/types/admin';

export interface AdminGuardOptions {
  requiredRole?: UserRole;
  fallbackPath?: string;
}

type Status = 'loading' | 'authorized' | 'unauthorized';

export function withAdminGuard<P extends object>(
  Component: React.ComponentType<P>,
  options: AdminGuardOptions = {}
): React.FC<P> {
  const { requiredRole, fallbackPath = '/' } = options;

  const GuardedComponent: React.FC<P> = (props) => {
    const [status, setStatus] = useState<Status>('loading');

    useEffect(() => {
      let user: AdminUser | null = null;

      try {
        const raw = localStorage.getItem('admin_user');
        if (raw) {
          user = JSON.parse(raw) as AdminUser;
        }
      } catch {
        user = null;
      }

      if (!user) {
        setStatus('unauthorized');
        return;
      }

      if (requiredRole && user.role !== requiredRole) {
        setStatus('unauthorized');
        return;
      }

      setStatus('authorized');
    }, []);

    if (status === 'loading') {
      return (
        <div data-testid="admin-guard-loading" className="flex items-center justify-center min-h-screen">
          <div className="text-slate-500">Loading...</div>
        </div>
      );
    }

    if (status === 'unauthorized') {
      return (
        <div
          data-testid="admin-guard-unauthorized"
          className="flex flex-col items-center justify-center min-h-screen gap-4"
        >
          <p className="text-slate-700 text-lg">You do not have permission to access this page.</p>
          <Link
            href={fallbackPath}
            className="text-blue-600 hover:underline"
            aria-label="Go to Home"
          >
            Go to Home
          </Link>
        </div>
      );
    }

    return <Component {...props} />;
  };

  GuardedComponent.displayName = `withAdminGuard(${Component.displayName ?? Component.name ?? 'Component'})`;

  return GuardedComponent;
}

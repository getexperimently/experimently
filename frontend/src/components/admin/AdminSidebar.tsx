import React from 'react';
import Link from 'next/link';

interface NavItem {
  label: string;
  href: string;
  testId: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', href: '/admin', testId: 'nav-item-dashboard', icon: '📊' },
  { label: 'Users', href: '/admin/users', testId: 'nav-item-users', icon: '👥' },
  { label: 'Roles', href: '/admin/roles', testId: 'nav-item-roles', icon: '🔑' },
  { label: 'Audit Log', href: '/admin/audit', testId: 'nav-item-audit', icon: '📋' },
  { label: 'Safety', href: '/admin/safety', testId: 'nav-item-safety', icon: '🛡️' },
  { label: 'Scheduler', href: '/admin/scheduler', testId: 'nav-item-scheduler', icon: '⏰' },
  { label: 'API Keys', href: '/admin/api-keys', testId: 'nav-item-api-keys', icon: '🗝️' },
];

interface AdminSidebarProps {
  currentPath: string;
}

export function AdminSidebar({ currentPath }: AdminSidebarProps) {
  return (
    <aside
      data-testid="admin-sidebar"
      className="w-56 min-h-screen bg-white border-r border-slate-200 flex flex-col"
    >
      <div className="px-4 py-6">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Navigation
        </p>
        <nav className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const isActive = currentPath === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                data-testid={item.testId}
                className={[
                  'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-blue-50 text-blue-700 border-r-2 border-blue-600'
                    : 'text-slate-600 hover:bg-slate-50',
                ].join(' ')}
              >
                <span role="img" aria-hidden="true">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}

import React from 'react';
import Link from 'next/link';
import { useEdition } from '@/contexts/EditionContext';
import { EDITIONS_DOC_PATH, EditionInfo, FEATURES, featureEnabled } from '@/services/edition';

interface NavItem {
  label: string;
  href: string;
  testId: string;
  icon: string;
  /**
   * Licence feature this item needs. Items without one are Community and
   * always render. This is the seam the coupling report calls out: `/admin/roles`
   * was hard-linked from Community chrome (`ee-coupling-report.md` §6).
   */
  feature?: string;
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', href: '/admin', testId: 'nav-item-dashboard', icon: '📊' },
  { label: 'Users', href: '/admin/users', testId: 'nav-item-users', icon: '👥' },
  {
    label: 'Roles',
    href: '/admin/roles',
    testId: 'nav-item-roles',
    icon: '🔑',
    feature: FEATURES.RBAC,
  },
  { label: 'Audit Log', href: '/admin/audit', testId: 'nav-item-audit', icon: '📋' },
  { label: 'Safety', href: '/admin/safety', testId: 'nav-item-safety', icon: '🛡️' },
  { label: 'Scheduler', href: '/admin/scheduler', testId: 'nav-item-scheduler', icon: '⏰' },
  { label: 'API Keys', href: '/admin/api-keys', testId: 'nav-item-api-keys', icon: '🗝️' },
  { label: 'Notifications', href: '/admin/notifications', testId: 'nav-item-notifications', icon: '🔔' },
];

/** Community items, plus any Enterprise item the licence currently allows. */
export function visibleNavItems(edition: EditionInfo, items: NavItem[] = NAV_ITEMS): NavItem[] {
  return items.filter((item) => !item.feature || featureEnabled(edition, item.feature));
}

interface AdminSidebarProps {
  currentPath: string;
}

export function AdminSidebar({ currentPath }: AdminSidebarProps) {
  const { info, isLoading } = useEdition();
  const items = visibleNavItems(info);
  // Not while the probe is outstanding: the note would say an admin page is
  // Enterprise-only on a licensed instance, then vanish when the answer came.
  const hiddenEnterprise = isLoading ? 0 : NAV_ITEMS.length - items.length;

  return (
    <aside
      data-testid="admin-sidebar"
      className="w-56 flex-shrink-0 bg-white border-r border-slate-200 flex flex-col"
    >
      <div className="px-4 py-6">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Navigation
        </p>
        <nav className="space-y-1">
          {items.map((item) => {
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

        {hiddenEnterprise > 0 && (
          <p data-testid="admin-sidebar-enterprise-note" className="mt-6 text-xs text-slate-400">
            {hiddenEnterprise === 1 ? 'One admin page is' : `${hiddenEnterprise} admin pages are`}{' '}
            part of{' '}
            <Link href={EDITIONS_DOC_PATH} className="underline hover:text-slate-600">
              Enterprise
            </Link>
            .
          </p>
        )}
      </div>
    </aside>
  );
}

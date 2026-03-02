import React from 'react';
import { AdminSidebar } from './AdminSidebar';

interface AdminLayoutProps {
  children: React.ReactNode;
  title: string;
  currentPath: string;
}

export function AdminLayout({ children, title, currentPath }: AdminLayoutProps) {
  return (
    <div data-testid="admin-layout" className="min-h-screen bg-slate-50 flex flex-col">
      {/* Top Header Bar */}
      <header className="bg-white border-b border-slate-200 h-14 flex items-center px-6 flex-shrink-0">
        <span className="text-lg font-semibold text-slate-900">Admin Panel</span>
        <span className="mx-3 text-slate-300">|</span>
        <span className="text-sm text-slate-600">{title}</span>
      </header>

      {/* Body: Sidebar + Content */}
      <div className="flex flex-1 overflow-hidden">
        <AdminSidebar currentPath={currentPath} />

        {/* Main Content Area */}
        <main className="flex-1 overflow-auto p-6">
          {children}
        </main>
      </div>
    </div>
  );
}

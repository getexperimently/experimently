import React, { useState } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { AuditLogFilter, AuditLogFilters } from '@/components/admin/audit/AuditLogFilter';
import { AuditLogTable } from '@/components/admin/audit/AuditLogTable';

export function AuditLogPage() {
  const [filters, setFilters] = useState<AuditLogFilters>({});

  return (
    <AdminLayout title="Audit Log" currentPath="/admin/audit">
      <div data-testid="audit-log-page" className="flex flex-col gap-5">
        <h2 className="text-xl font-semibold text-slate-900">Audit Log</h2>
        <AuditLogFilter filters={filters} onFilterChange={setFilters} />
        <AuditLogTable filters={filters} />
      </div>
    </AdminLayout>
  );
}

export default AuditLogPage;

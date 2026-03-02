import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AdminService } from '@/services/admin';
import { AdminUser, ROLE_COLORS, USER_ROLE_LABELS, UserListResponse } from '@/types/admin';

// eslint-disable-next-line @typescript-eslint/no-empty-interface
interface UserTableProps {}

export function UserTable(_props: UserTableProps) {
  const [data, setData] = useState<UserListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchUsers = useCallback(async (searchTerm?: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await AdminService.listUsers({
        page: 1,
        limit: 50,
        ...(searchTerm ? { search: searchTerm } : {}),
      });
      setData(result);
    } catch (err) {
      setError((err as Error).message || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearch(value);
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      fetchUsers(value || undefined);
    }, 300);
  };

  const handleDelete = async (user: AdminUser) => {
    const confirmed = window.confirm(
      `Are you sure you want to delete user "${user.username}"? This action cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await AdminService.deleteUser(user.id);
      // Refetch after deletion
      await fetchUsers(search || undefined);
    } catch (err) {
      alert(`Failed to delete user: ${(err as Error).message}`);
    }
  };

  return (
    <div data-testid="user-table" className="bg-white rounded-lg border border-slate-200 overflow-hidden">
      {/* Search */}
      <div className="p-4 border-b border-slate-200">
        <input
          data-testid="user-search"
          type="text"
          placeholder="Search by name or email..."
          value={search}
          onChange={handleSearchChange}
          className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Loading Skeleton */}
      {loading && (
        <div data-testid="loading-skeleton" className="divide-y divide-slate-100">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-6 py-4 animate-pulse">
              <div className="h-4 bg-slate-200 rounded w-1/4" />
              <div className="h-4 bg-slate-200 rounded w-1/3" />
              <div className="h-5 bg-slate-200 rounded w-16" />
              <div className="h-5 bg-slate-200 rounded w-12" />
            </div>
          ))}
        </div>
      )}

      {/* Error State */}
      {!loading && error && (
        <div
          data-testid="error-state"
          className="p-8 text-center text-red-600"
        >
          <p className="font-medium">Failed to load users</p>
          <p className="text-sm mt-1 text-red-500">{error}</p>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && data && data.items.length === 0 && (
        <div className="p-8 text-center text-slate-500">
          <p>No users found</p>
        </div>
      )}

      {/* Table */}
      {!loading && !error && data && data.items.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600 uppercase text-xs tracking-wide">
                <tr>
                  <th className="px-6 py-3 text-left">Username</th>
                  <th className="px-6 py-3 text-left">Email</th>
                  <th className="px-6 py-3 text-left">Role</th>
                  <th className="px-6 py-3 text-left">Status</th>
                  <th className="px-6 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((user) => (
                  <tr key={user.id} className="hover:bg-slate-50">
                    <td className="px-6 py-4 font-medium text-slate-900">{user.username}</td>
                    <td className="px-6 py-4 text-slate-600">{user.email}</td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${ROLE_COLORS[user.role]}`}
                      >
                        {USER_ROLE_LABELS[user.role]}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      {user.is_active ? (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                          Active
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600">
                          Inactive
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <button
                        data-testid={`delete-user-${user.id}`}
                        onClick={() => handleDelete(user)}
                        className="text-red-600 hover:text-red-800 text-sm font-medium"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination Info */}
          <div className="px-6 py-3 border-t border-slate-200 text-sm text-slate-500">
            Showing {data.items.length} of {data.total} users
          </div>
        </>
      )}
    </div>
  );
}

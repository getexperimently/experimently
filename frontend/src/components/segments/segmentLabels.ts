import type { SegmentKind, SegmentStatus } from '@/services/segments';

export const STATUS_LABELS: Record<SegmentStatus, string> = {
  active: 'Active',
  inactive: 'Inactive',
  archived: 'Archived',
};

export const STATUS_COLORS: Record<SegmentStatus, string> = {
  active: 'bg-green-100 text-green-800',
  inactive: 'bg-slate-100 text-slate-700',
  archived: 'bg-amber-100 text-amber-900',
};

export const KIND_LABELS: Record<SegmentKind, string> = {
  rules: 'Rules',
  id_list: 'ID list',
};

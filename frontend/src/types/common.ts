import { AdminUser } from './admin';

export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  message: string;
  variant: ToastVariant;
  duration?: number;
}

export type AuthUser = AdminUser;

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export type FormErrors<T> = Partial<Record<keyof T, string>>;

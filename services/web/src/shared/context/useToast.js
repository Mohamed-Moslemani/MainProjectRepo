import { useContext } from 'react';
import { ToastContext } from './ToastContext';

/**
 * Hook for firing app-wide toasts.
 *
 *   const toast = useToast();
 *   toast.success('Saved');
 *   toast.error(err.response?.data?.detail || 'Something went wrong');
 *
 * Returns: { success, error, info, warning, dismiss }
 *
 * Throws if used outside <ToastProvider> — use ToastContext directly
 * if you need a non-throwing read.
 */
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used inside <ToastProvider>');
  }
  return ctx;
}

'use client';

import { createContext, useCallback, useContext, useState } from 'react';

// ─── Toast ─────────────────────────────────────────────────────────────────────

type ToastVariant = 'error' | 'success' | 'warning' | 'info';

interface ToastItem {
  id: number;
  variant: ToastVariant;
  message: string;
}

interface ToastContextValue {
  error: (msg: string) => void;
  success: (msg: string) => void;
  warning: (msg: string) => void;
  info: (msg: string) => void;
}

// ─── Confirm ──────────────────────────────────────────────────────────────────

interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  destructive?: boolean;
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

// ─── Contexts ─────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastContextValue>({
  error: () => {},
  success: () => {},
  warning: () => {},
  info: () => {},
});

const ConfirmContext = createContext<ConfirmFn>(() => Promise.resolve(false));

// ─── Provider ─────────────────────────────────────────────────────────────────

let _nextId = 0;

export function AppNotificationsProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [confirmState, setConfirmState] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);

  const push = useCallback((variant: ToastVariant, message: string) => {
    const id = ++_nextId;
    setToasts((prev) => [...prev, { id, variant, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const toastApi: ToastContextValue = {
    error: (msg) => push('error', msg),
    success: (msg) => push('success', msg),
    warning: (msg) => push('warning', msg),
    info: (msg) => push('info', msg),
  };

  const confirm: ConfirmFn = useCallback(
    (opts) => new Promise<boolean>((resolve) => setConfirmState({ ...opts, resolve })),
    [],
  );

  const handleResult = (result: boolean) => {
    if (confirmState) {
      confirmState.resolve(result);
      setConfirmState(null);
    }
  };

  return (
    <ToastContext.Provider value={toastApi}>
      <ConfirmContext.Provider value={confirm}>
        {children}

        {/* Toast stack — bottom-right */}
        <div className="fixed bottom-5 right-5 z-[200] flex flex-col gap-2 pointer-events-none">
          {toasts.map((t) => (
            <AppToastItem
              key={t.id}
              toast={t}
              onDismiss={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
            />
          ))}
        </div>

        {/* Confirm modal */}
        {confirmState && (
          <AppConfirmModal
            title={confirmState.title}
            message={confirmState.message}
            confirmLabel={confirmState.confirmLabel}
            destructive={confirmState.destructive}
            onConfirm={() => handleResult(true)}
            onCancel={() => handleResult(false)}
          />
        )}
      </ConfirmContext.Provider>
    </ToastContext.Provider>
  );
}

export function useAppToast() {
  return useContext(ToastContext);
}

export function useAppConfirm() {
  return useContext(ConfirmContext);
}

// ─── Toast item ───────────────────────────────────────────────────────────────

const VARIANT_STYLES: Record<ToastVariant, { pill: string; icon: string }> = {
  error:   { pill: 'bg-red-500',   icon: '✕' },
  success: { pill: 'bg-green-500', icon: '✓' },
  warning: { pill: 'bg-amber-500', icon: '!' },
  info:    { pill: 'bg-blue-500',  icon: 'i' },
};

const BORDER_STYLES: Record<ToastVariant, string> = {
  error:   'border-red-500/30',
  success: 'border-green-500/30',
  warning: 'border-amber-500/30',
  info:    'border-blue-500/30',
};

function AppToastItem({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  const s = VARIANT_STYLES[toast.variant];
  return (
    <div
      className={`pointer-events-auto flex items-start gap-3 w-80 bg-zinc-900 border ${BORDER_STYLES[toast.variant]} rounded-xl shadow-2xl p-4 animate-in slide-in-from-right-full duration-200`}
    >
      <div
        className={`mt-0.5 w-5 h-5 rounded-full ${s.pill} flex items-center justify-center text-white text-[10px] font-bold shrink-0`}
      >
        {s.icon}
      </div>
      <p className="flex-1 text-sm text-zinc-200 leading-snug break-words">{toast.message}</p>
      <button
        onClick={onDismiss}
        className="text-zinc-600 hover:text-zinc-300 transition-colors text-xs shrink-0 mt-0.5"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}

// ─── Confirm modal ────────────────────────────────────────────────────────────

function AppConfirmModal({
  title,
  message,
  confirmLabel = 'Confirm',
  destructive = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onCancel} />

      {/* Card */}
      <div className="relative bg-zinc-900 border border-zinc-700 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-in zoom-in-95 duration-150">
        {/* Icon */}
        {destructive && (
          <div className="w-10 h-10 rounded-full bg-red-500/15 border border-red-500/30 flex items-center justify-center mb-4">
            <span className="text-red-400 text-lg font-bold">!</span>
          </div>
        )}

        <h2 className="text-lg font-semibold text-white mb-2">{title}</h2>
        <p className="text-sm text-zinc-400 leading-relaxed mb-6">{message}</p>

        <div className="flex items-center justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-zinc-400 hover:text-zinc-200 transition-colors rounded-lg hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`px-5 py-2 text-sm font-medium rounded-lg transition-colors ${
              destructive
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-blue-600 hover:bg-blue-500 text-white'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

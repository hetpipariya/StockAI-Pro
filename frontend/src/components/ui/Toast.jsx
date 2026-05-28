import React, { createContext, useContext, useMemo, useState, useCallback } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from 'lucide-react';

const ToastContext = createContext(null);

const toastTone = {
  success: {
    icon: CheckCircle2,
    style: 'border-emerald-300/45 bg-emerald-500/15 text-emerald-100',
  },
  error: {
    icon: AlertCircle,
    style: 'border-rose-300/45 bg-rose-500/15 text-rose-100',
  },
  warning: {
    icon: AlertTriangle,
    style: 'border-amber-300/45 bg-amber-500/15 text-amber-100',
  },
  info: {
    icon: Info,
    style: 'border-cyan-300/45 bg-cyan-500/15 text-cyan-100',
  },
};

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);

  const showToast = useCallback((message, type = 'info', duration = 3200) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((prev) => {
      const next = [...prev, { id, message, type }];
      if (next.length > 4) next.shift();
      return next;
    });

    setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, duration);
  }, []);

  const contextValue = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-[min(92vw,360px)] flex-col gap-2">
        {toasts.map((toast) => {
          const tone = toastTone[toast.type] || toastTone.info;
          const Icon = tone.icon;

          return (
            <div
              key={toast.id}
              className={`pointer-events-auto rounded-xl border px-3.5 py-3 text-sm shadow-[0_14px_30px_rgba(2,8,23,0.45)] backdrop-blur-sm animate-in slide-in-from-right-5 fade-in duration-300 ${tone.style}`}
              role="status"
              aria-live="polite"
            >
              <div className="flex items-start gap-2.5">
                <Icon className="mt-0.5 h-4.5 w-4.5 shrink-0" />
                <p className="leading-relaxed">{toast.message}</p>
              </div>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return context;
};

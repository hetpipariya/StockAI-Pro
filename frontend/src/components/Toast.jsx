import React, { useEffect, useState, useContext, createContext } from 'react';
import { CheckCircle, AlertCircle, Info, X } from 'lucide-react';

export const ToastContext = createContext();

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return context;
};

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);

  const showToast = (message, type = 'info', duration = 3000) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, message, type }]);

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, duration);
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <ToastContainer toasts={toasts} />
    </ToastContext.Provider>
  );
};

export const ToastContainer = ({ toasts }) => {
  return (
    <div className="fixed bottom-4 right-4 space-y-2 z-40">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-in fade-in slide-in-from-bottom-2 ${
            toast.type === 'success'
              ? 'bg-green-900/20 text-green-400 border border-green-500/20'
              : toast.type === 'error'
              ? 'bg-red-900/20 text-red-400 border border-red-500/20'
              : 'bg-blue-900/20 text-blue-400 border border-blue-500/20'
          }`}
        >
          {toast.type === 'success' && <CheckCircle className="w-5 h-5" />}
          {toast.type === 'error' && <AlertCircle className="w-5 h-5" />}
          {toast.type === 'info' && <Info className="w-5 h-5" />}
          <span>{toast.message}</span>
        </div>
      ))}
    </div>
  );
};
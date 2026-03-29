import React, { createContext, useContext, useState, useCallback } from 'react';

const ToastContext = createContext();

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);

  const showToast = useCallback((message, type = 'info') => {
    const id = Date.now();
    setToasts(prev => {
      // Keep max 3 toasts
      const active = [...prev, { id, message, type }];
      if (active.length > 3) active.shift();
      return active;
    });

    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 3000);
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div style={{
        position: 'fixed',
        top: '20px',
        right: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        zIndex: 9999,
        pointerEvents: 'none',
        fontFamily: 'var(--font-family-base, sans-serif)'
      }}>
        {toasts.map(toast => {
          let bg = 'var(--card, #0C1118)';
          let border = 'var(--primary, #00FF9F)';
          if (toast.type === 'error') border = '#FF4C4C';
          else if (toast.type === 'warning') border = '#FFB347';
          else if (toast.type === 'info') border = '#8A9BB0';

          return (
            <div key={toast.id} style={{
              background: bg,
              color: '#fff',
              borderLeft: `4px solid ${border}`,
              padding: '12px 20px',
              borderRadius: '4px',
              boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
              fontSize: '13px',
              animation: 'slideInRight 0.3s ease forwards',
              minWidth: '250px'
            }}>
              {toast.message}
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => useContext(ToastContext);

import { create } from 'zustand';
import { Notification, NotificationType } from './types';
import { v4 as uuidv4 } from 'uuid';

interface UIStoreState {
  sidebarOpen: boolean;
  notifications: Notification[];
  theme: 'dark' | 'light';
  selectedSymbol: string | null;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  addNotification: (message: string, type: NotificationType, duration?: number) => void;
  removeNotification: (id: string) => void;
  clearNotifications: () => void;
  setTheme: (theme: 'dark' | 'light') => void;
  setSelectedSymbol: (symbol: string | null) => void;
}

export const useUIStore = create<UIStoreState>((set, get) => ({
  sidebarOpen: true,
  notifications: [],
  theme: (localStorage.getItem('ui_theme') as 'dark' | 'light') || 'dark',
  selectedSymbol: null,

  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),

  setSidebarOpen: (open) => set({ sidebarOpen: open }),

  addNotification: (message, type, duration = 3000) => {
    const id = uuidv4();
    const notification: Notification = {
      id,
      message,
      type,
      duration,
      timestamp: Date.now(),
    };

    set((state) => ({
      notifications: [...state.notifications, notification],
    }));

    if (duration > 0) {
      setTimeout(() => {
        get().removeNotification(id);
      }, duration);
    }
  },

  removeNotification: (id) => {
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    }));
  },

  clearNotifications: () => set({ notifications: [] }),

  setTheme: (theme) => {
    localStorage.setItem('ui_theme', theme);
    set({ theme });
  },

  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),
}));

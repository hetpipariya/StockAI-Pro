import { useEffect } from 'react';
import { useStore } from '../store/useStore.js';
import { useAuthStore } from '../store/useAuthStore.js';
import { wsManager } from '../api/websocket.js';

export function AppInitializer({ children }) {
  const { fetchInitialData } = useStore(); 
  const { isAuthenticated, checkAuth } = useAuthStore();
  
  useEffect(() => {
    void checkAuth();
  }, [checkAuth]);
  
  useEffect(() => { 
    if (isAuthenticated) { 
      void fetchInitialData(); 
      wsManager.connect(); 
      return;
    } 

    wsManager.disconnect();
  }, [fetchInitialData, isAuthenticated]);
  
  return children;
}
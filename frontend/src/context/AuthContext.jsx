import React, { createContext, useCallback, useContext, useMemo } from 'react';
import { useAuthStore } from '../store/useAuthStore.js';
import {
  clearStoredAuthTokens,
  getStoredAccessToken,
  getStoredRefreshToken,
} from '../utils/authStorage.js';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isLoading = useAuthStore((s) => s.isLoading);
  const storeLogin = useAuthStore((s) => s.login);
  const storeLogout = useAuthStore((s) => s.logout);
  const storeSignup = useAuthStore((s) => s.signup);

  const accessToken = getStoredAccessToken();
  const refreshToken = getStoredRefreshToken();

  const login = useCallback(
    async ({ email, password }) => {
      const ok = await storeLogin({ email, password });
      if (!ok) {
        throw new Error(useAuthStore.getState().error || 'Login failed');
      }
      return useAuthStore.getState().user;
    },
    [storeLogin],
  );

  const signup = useCallback(
    async ({ username: _username, email, password }) => {
      const u = await storeSignup({ email, password });
      return u;
    },
    [storeSignup],
  );

  const logout = useCallback(async () => {
    await storeLogout();
  }, [storeLogout]);

  const clearSession = useCallback(() => {
    clearStoredAuthTokens();
    useAuthStore.setState({ user: null, isAuthenticated: false, error: null });
  }, []);

  const value = useMemo(
    () => ({
      user,
      accessToken,
      refreshToken,
      isAuthenticated,
      isLoading,
      login,
      signup,
      logout,
      clearSession,
    }),
    [
      user,
      accessToken,
      refreshToken,
      isAuthenticated,
      isLoading,
      login,
      signup,
      logout,
      clearSession,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

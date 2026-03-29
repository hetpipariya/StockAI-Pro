import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import { api, clearStoredAuth, getStoredAccessToken, getStoredRefreshToken, getStoredUser, setStoredAuth } from '../api/api';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(getStoredUser());
  const [accessToken, setAccessToken] = useState(getStoredAccessToken());
  const [refreshToken, setRefreshToken] = useState(getStoredRefreshToken());
  const [isLoading, setIsLoading] = useState(true);

  const applySession = useCallback(({ nextUser, nextAccessToken, nextRefreshToken }) => {
    setUser(nextUser || null);
    setAccessToken(nextAccessToken || '');
    setRefreshToken(nextRefreshToken || '');
    setStoredAuth({
      user: nextUser || null,
      accessToken: nextAccessToken || '',
      refreshToken: nextRefreshToken || '',
    });
  }, []);

  const clearSession = useCallback(() => {
    setUser(null);
    setAccessToken('');
    setRefreshToken('');
    clearStoredAuth();
  }, []);

  const extractAuthSession = useCallback((payload, fallbackUsername = '') => {
    const nextAccessToken = payload?.access_token || payload?.accessToken || '';
    const nextRefreshToken = payload?.refresh_token || payload?.refreshToken || '';
    const nextUser =
      payload?.user ||
      (payload?.username ? { username: payload.username } : null) ||
      (fallbackUsername ? { username: fallbackUsername } : null);

    return {
      nextUser,
      nextAccessToken,
      nextRefreshToken,
    };
  }, []);

  const bootstrapAuth = useCallback(async () => {
    const initialAccess = getStoredAccessToken();
    const initialRefresh = getStoredRefreshToken();
    const initialUser = getStoredUser();

    if (!initialAccess && !initialRefresh) {
      setIsLoading(false);
      return;
    }

    try {
      if (initialAccess) {
        const me = await api.me();
        applySession({
          nextUser: me,
          nextAccessToken: initialAccess,
          nextRefreshToken: initialRefresh,
        });
        setIsLoading(false);
        return;
      }
    } catch (_) {
      // Fall through to refresh path.
    }

    if (!initialRefresh) {
      clearSession();
      setIsLoading(false);
      return;
    }

    try {
      const refreshed = await api.refresh(initialRefresh);
      const nextAccessToken = refreshed?.access_token || '';
      const nextRefreshToken = refreshed?.refresh_token || initialRefresh;
      setStoredAuth({
        user: initialUser,
        accessToken: nextAccessToken,
        refreshToken: nextRefreshToken,
      });
      const me = await api.me();
      applySession({
        nextUser: me,
        nextAccessToken,
        nextRefreshToken,
      });
    } catch (_) {
      clearSession();
    } finally {
      setIsLoading(false);
    }
  }, [applySession, clearSession]);

  useEffect(() => {
    bootstrapAuth();
  }, [bootstrapAuth]);

  const login = useCallback(
    async ({ username, password }) => {
      const data = await api.login({ username, password });
      const {
        nextUser: parsedUser,
        nextAccessToken,
        nextRefreshToken,
      } = extractAuthSession(data, username?.trim?.());

      if (!nextAccessToken) {
        throw new Error('Invalid login response from server');
      }

      let nextUser = parsedUser;
      if (!nextUser) {
        try {
          nextUser = await api.me();
        } catch (_) {
          nextUser = { username: username?.trim?.() || 'user' };
        }
      }

      applySession({ nextUser, nextAccessToken, nextRefreshToken });
      return nextUser;
    },
    [applySession, extractAuthSession]
  );

  const signup = useCallback(
    async ({ username, email, password }) => {
      let data = await api.signup({ username, email, password });
      let {
        nextUser: parsedUser,
        nextAccessToken,
        nextRefreshToken,
      } = extractAuthSession(data, username?.trim?.());

      // Legacy backend may return signup success without tokens; perform login fallback.
      if (!nextAccessToken) {
        data = await api.login({ username, password });
        ({
          nextUser: parsedUser,
          nextAccessToken,
          nextRefreshToken,
        } = extractAuthSession(data, username?.trim?.()));
      }

      if (!nextAccessToken) {
        throw new Error('Invalid signup response from server');
      }

      let nextUser = parsedUser;
      if (!nextUser) {
        try {
          nextUser = await api.me();
        } catch (_) {
          nextUser = { username: username?.trim?.() || 'user' };
        }
      }

      applySession({ nextUser, nextAccessToken, nextRefreshToken });
      return nextUser;
    },
    [applySession, extractAuthSession]
  );

  const logout = useCallback(async () => {
    try {
      if (accessToken) {
        await api.logout();
      }
    } catch (_) {
      // Ignore logout API failures and clear local session anyway.
    } finally {
      clearSession();
    }
  }, [accessToken, clearSession]);

  const value = useMemo(
    () => ({
      user,
      accessToken,
      refreshToken,
      isAuthenticated: Boolean(accessToken),
      isLoading,
      login,
      signup,
      logout,
      clearSession,
    }),
    [user, accessToken, refreshToken, isLoading, login, signup, logout, clearSession]
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

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const LEGACY_ACCESS_TOKEN_KEY = 'stockai_access_token';
const LEGACY_REFRESH_TOKEN_KEY = 'stockai_refresh_token';
const LEGACY_AUTH_KEY = 'stockai-auth';

const safeParse = (value) => {
  try {
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
};

const readLegacyAuth = () => {
  const legacyAuth = safeParse(localStorage.getItem(LEGACY_AUTH_KEY));
  return legacyAuth && typeof legacyAuth === 'object' ? legacyAuth : null;
};

export const getStoredAccessToken = () => {
  try {
    return (
      localStorage.getItem(ACCESS_TOKEN_KEY) ||
      localStorage.getItem(LEGACY_ACCESS_TOKEN_KEY) ||
      readLegacyAuth()?.accessToken ||
      ''
    );
  } catch {
    return '';
  }
};

export const getStoredRefreshToken = () => {
  try {
    return (
      localStorage.getItem(REFRESH_TOKEN_KEY) ||
      localStorage.getItem(LEGACY_REFRESH_TOKEN_KEY) ||
      readLegacyAuth()?.refreshToken ||
      ''
    );
  } catch {
    return '';
  }
};

export const getStoredAuthUser = () => {
  try {
    return readLegacyAuth()?.user || null;
  } catch {
    return null;
  }
};

export const setStoredAuthTokens = ({ accessToken = '', refreshToken = '', user = null }) => {
  try {
    if (accessToken) {
      localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
      localStorage.setItem(LEGACY_ACCESS_TOKEN_KEY, accessToken);
    } else {
      localStorage.removeItem(ACCESS_TOKEN_KEY);
      localStorage.removeItem(LEGACY_ACCESS_TOKEN_KEY);
    }

    if (refreshToken) {
      localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
      localStorage.setItem(LEGACY_REFRESH_TOKEN_KEY, refreshToken);
    } else {
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
    }

    if (user) {
      localStorage.setItem(LEGACY_AUTH_KEY, JSON.stringify({ accessToken, refreshToken, user }));
    } else if (!accessToken && !refreshToken) {
      localStorage.removeItem(LEGACY_AUTH_KEY);
    }
  } catch {
    // Ignore storage failures in restricted browser contexts.
  }
};

export const clearStoredAuthTokens = () => {
  try {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(LEGACY_ACCESS_TOKEN_KEY);
    localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
    localStorage.removeItem(LEGACY_AUTH_KEY);
  } catch {
    // Ignore storage failures in restricted browser contexts.
  }
};
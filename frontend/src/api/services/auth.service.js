import axios from 'axios';
import { apiClient } from '../client.js';
import { API_ENDPOINTS } from '../endpoints.js';

const AUTH_TIMEOUT_MS = 10000;

const trimTrailingSlash = (value) => String(value || '').trim().replace(/\/$/, '');

const isLoopbackOrigin = (value) => {
    const normalized = trimTrailingSlash(value);
    if (!normalized) return false;

    try {
        const hostname = new URL(normalized).hostname;
        return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0';
    } catch {
        return false;
    }
};

const withApiV1 = (baseUrl) => {
    const normalized = trimTrailingSlash(baseUrl);
    if (!normalized) return '';
    if (normalized.endsWith('/api/v1')) return normalized;
    if (normalized.endsWith('/api')) return `${normalized}/v1`;
    return `${normalized}/api/v1`;
};

const getLoginFallbackUrls = () => {
    const envApiBase = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL);
    const browserOrigin = typeof window !== 'undefined' ? trimTrailingSlash(window.location.origin) : '';

    const shouldUseBrowserOrigin =
        Boolean(browserOrigin) &&
        !isLoopbackOrigin(browserOrigin) &&
        (!envApiBase || isLoopbackOrigin(envApiBase));

    const candidateBases = shouldUseBrowserOrigin
        ? [browserOrigin]
        : [envApiBase, browserOrigin].filter(Boolean);

    return [...new Set(candidateBases)]
        .map(withApiV1)
        .filter(Boolean)
        .map((base) => `${base}/auth/login`);
};

const shouldRetryWithFallback = (error) => {
    const status = error?.status ?? error?.response?.status;
    if (status === 404 || status === 405 || status === 502 || status === 503 || status === 504) return true;
    return !error?.response;
};

const requestRelative = async (method, path, payload) => {
    if (method === 'get') return apiClient.get(path);
    return apiClient.post(path, payload);
};

const requestWithRelativeFallbacks = async (method, primaryPath, payload, fallbackPaths = []) => {
    const candidates = [primaryPath, ...fallbackPaths];
    let lastError = null;

    for (const path of candidates) {
        try {
            return await requestRelative(method, path, payload);
        } catch (error) {
            lastError = error;
            const isLast = path === candidates[candidates.length - 1];
            if (isLast || !shouldRetryWithFallback(error)) {
                throw error;
            }
        }
    }

    throw lastError || new Error('Auth request failed');
};

const requestWithAbsoluteFallbacks = async (payload, urls) => {
    let lastError = null;

    for (const url of urls) {
        try {
            const response = await axios.post(url, payload, {
                timeout: AUTH_TIMEOUT_MS,
                headers: {
                    'Content-Type': 'application/json',
                    'X-Client-Version': '2.0.0',
                },
            });
            return response.data;
        } catch (error) {
            lastError = error;
            const isLast = url === urls[urls.length - 1];
            if (isLast || !shouldRetryWithFallback(error)) {
                throw error;
            }
        }
    }

    throw lastError || new Error('Auth fallback request failed');
};

export const AuthService = {
    login: async (username, password) => {
        const body = { username, password };

        try {
            return await requestWithRelativeFallbacks(
                'post',
                API_ENDPOINTS.AUTH.LOGIN,
                body,
                [],
            );
        } catch (error) {
            if (!shouldRetryWithFallback(error)) {
                throw error;
            }

            const fallbackUrls = getLoginFallbackUrls();
            if (!fallbackUrls.length) {
                throw error;
            }

            return requestWithAbsoluteFallbacks(body, fallbackUrls);
        }
    },

    refresh: (refreshToken) => requestWithRelativeFallbacks(
        'post',
        API_ENDPOINTS.AUTH.REFRESH,
        { refresh_token: refreshToken },
        [],
    ),

    logout: () => requestWithRelativeFallbacks(
        'post',
        API_ENDPOINTS.AUTH.LOGOUT,
        undefined,
        [],
    ),

    me: () => requestWithRelativeFallbacks(
        'get',
        API_ENDPOINTS.AUTH.ME,
        undefined,
        [],
    ),
};
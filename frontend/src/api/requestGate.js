export const API_TIMEOUT_MS = 500;
export const MAX_API_RETRIES = 2;
export const API_TIMEOUT_MAX_MS = 12000;

export const LATENCY_LIVE_MS = 500;
export const LATENCY_MAX_MS = 1000;
export const LATENCY_OVERLOAD_MS = 5000;

const DEFAULT_SINGLE_FLIGHT_KEY = 'global';
const activeRequestControllers = new Map();
let activeRequestToken = 0;

const normalizeSingleFlightKey = (key) => {
  if (key === null || key === undefined) return DEFAULT_SINGLE_FLIGHT_KEY;
  const normalized = String(key).trim();
  return normalized || DEFAULT_SINGLE_FLIGHT_KEY;
};

const abortController = (controller, reason = 'request_cancelled') => {
  if (!controller) return;
  try {
    controller.abort(reason);
  } catch {
    // Ignore abort errors to keep fail-fast behavior deterministic.
  }
};

export const isAbortLikeError = (error) => {
  const message = String(error?.message || '');
  return (
    error?.name === 'AbortError'
    || error?.code === 'ERR_CANCELED'
    || /abort/i.test(message)
    || /canceled|cancelled/i.test(message)
  );
};

export const beginSingleFlightRequest = ({ externalSignal, key } = {}) => {
  const requestKey = normalizeSingleFlightKey(key);
  const previousController = activeRequestControllers.get(requestKey);
  if (previousController) {
    abortController(previousController, 'superseded_by_new_request');
  }

  const controller = new AbortController();
  const requestToken = ++activeRequestToken;
  activeRequestControllers.set(requestKey, controller);

  let detachExternal = null;
  if (externalSignal) {
    if (externalSignal.aborted) {
      abortController(controller, 'external_abort');
    } else {
      const onExternalAbort = () => abortController(controller, 'external_abort');
      externalSignal.addEventListener('abort', onExternalAbort, { once: true });
      detachExternal = () => externalSignal.removeEventListener('abort', onExternalAbort);
    }
  }

  const release = () => {
    if (detachExternal) detachExternal();
    if (activeRequestControllers.get(requestKey) === controller) {
      activeRequestControllers.delete(requestKey);
    }
  };

  return {
    requestToken,
    key: requestKey,
    signal: controller.signal,
    abort: (reason = 'request_cancelled') => abortController(controller, reason),
    release,
  };
};

export const cancelActiveRequest = (reason = 'request_cancelled', key = null) => {
  if (key !== null && key !== undefined) {
    const requestKey = normalizeSingleFlightKey(key);
    const controller = activeRequestControllers.get(requestKey);
    if (!controller) return;
    abortController(controller, reason);
    activeRequestControllers.delete(requestKey);
    return;
  }

  for (const controller of activeRequestControllers.values()) {
    abortController(controller, reason);
  }
  activeRequestControllers.clear();
};

export const normalizeTimeoutMs = (value, fallback = API_TIMEOUT_MS) => {
  const parsed = Number(value);
  const safeFallback = Number.isFinite(fallback) ? fallback : API_TIMEOUT_MS;
  const resolved = Number.isFinite(parsed) && parsed > 0 ? parsed : safeFallback;
  return Math.max(API_TIMEOUT_MS, Math.min(API_TIMEOUT_MAX_MS, resolved));
};

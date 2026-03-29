/**
 * @file useApi.js
 * Custom hook to manage API fetching state.
 */
import { useState, useEffect, useCallback } from 'react';

/**
 * Hook to wrap an API call and manage loading/error/data states.
 * @param {Function} apiFn - The async function that fetches data
 * @param {Array} deps - Dependency array to trigger refetch
 * @returns {Object} { data, loading, error, refetch }
 */
export function useApi(apiFn, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const execute = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiFn();
      setData(result);
      return result;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [apiFn]);

  useEffect(() => {
    execute().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, refetch: execute };
}

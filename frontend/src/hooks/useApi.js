import { useState } from 'react';

export function useApi(apiFunc) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const execute = async (...args) => {
    try {
      setLoading(true);
      setError(null);
      const result = await apiFunc(...args);
      setData(result);
      return result;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  return { data, error, loading, execute };
}
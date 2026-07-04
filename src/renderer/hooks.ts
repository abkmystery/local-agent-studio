import { useCallback, useEffect, useState } from 'react';

export function useLoader<T>(loader: () => Promise<T>, dependencies: unknown[] = []) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      setData(await loader());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
  useEffect(() => { void reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

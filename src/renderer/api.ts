const desktop = typeof window === 'undefined' ? undefined : window.localStudio;

function connection() {
  if (!desktop) {
    throw new Error('Desktop security bridge unavailable. Restart Local Agent Studio or reinstall the latest build.');
  }
  return desktop;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { apiBase, token } = connection();
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      'x-studio-token': token,
      ...(init.body instanceof FormData ? {} : { 'content-type': 'application/json' }),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Retain the HTTP status when a service returns non-JSON.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, data: FormData) => request<T>(path, { method: 'POST', body: data }),
  download: async (path: string) => {
    const { apiBase, token } = connection();
    const response = await fetch(`${apiBase}${path}`, { headers: { 'x-studio-token': token } });
    if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
    return response.blob();
  },
  get headers() {
    return { 'x-studio-token': connection().token };
  },
};

export function formatBytes(value?: number): string {
  if (value === undefined || value === null) return 'Unknown';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

export function timeAgo(value: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

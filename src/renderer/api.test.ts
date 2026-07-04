import { describe, expect, it } from 'vitest';
import { api, formatBytes, timeAgo } from './api';

describe('display utilities', () => {
  it('formats model sizes for humans', () => {
    expect(formatBytes(5 * 1024 ** 3)).toBe('5.0 GB');
  });

  it('formats recent activity', () => {
    expect(timeAgo(new Date(Date.now() - 90_000).toISOString())).toBe('1m ago');
  });

  it('reports a missing desktop bridge without attempting a fallback connection', async () => {
    await expect(api.get('/health')).rejects.toThrow('Desktop security bridge unavailable');
  });
});

import { contextBridge } from 'electron';

function argument(name: string): string {
  const prefix = `--${name}=`;
  const value = process.argv.find((item) => item.startsWith(prefix));
  if (!value) throw new Error(`Missing desktop argument: ${name}`);
  return value.slice(prefix.length);
}

contextBridge.exposeInMainWorld('localStudio', {
  apiBase: argument('studio-api'),
  token: argument('studio-token'),
  platform: process.platform,
});

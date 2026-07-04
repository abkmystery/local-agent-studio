import { app, BrowserWindow, Menu, Tray, nativeImage, shell } from 'electron';
import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process';
import crypto from 'node:crypto';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let backend: ChildProcessWithoutNullStreams | null = null;
let isQuitting = false;

function reservePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        reject(new Error('Unable to reserve a local port'));
        return;
      }
      server.close(() => resolve(address.port));
    });
  });
}

function waitForBackend(port: number, token: string, timeoutMs = 60_000): Promise<void> {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const poll = () => {
      const request = http.get(
        { host: '127.0.0.1', port, path: '/health', headers: { 'x-studio-token': token } },
        (response) => {
          response.resume();
          if (response.statusCode === 200) resolve();
          else retry();
        },
      );
      request.on('error', retry);
      request.setTimeout(1_000, () => request.destroy());
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error('The local service did not start in time.'));
      } else {
        setTimeout(poll, 250);
      }
    };
    poll();
  });
}

async function startBackend(): Promise<{ port: number; token: string }> {
  const port = await reservePort();
  const token = crypto.randomBytes(32).toString('hex');
  const dataDir = app.getPath('userData');
  const commonArgs = [
    '--host', '127.0.0.1',
    '--port', String(port),
    '--data-dir', dataDir,
    '--auth-token', token,
  ];

  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'backend', 'local-agent-backend.exe');
    backend = spawn(executable, [
      ...commonArgs,
      '--runtime-dir', path.join(process.resourcesPath, 'runtime'),
    ], { windowsHide: true });
  } else {
    const python = process.env.LOCAL_AGENT_PYTHON || 'python';
    backend = spawn(python, ['-m', 'backend.app', ...commonArgs], {
      cwd: app.getAppPath(),
      windowsHide: true,
    });
  }

  backend.stdout.on('data', (chunk) => console.log(`[backend] ${String(chunk).trimEnd()}`));
  backend.stderr.on('data', (chunk) => console.error(`[backend] ${String(chunk).trimEnd()}`));
  backend.once('exit', (code) => {
    if (!isQuitting) console.error(`Local service stopped unexpectedly (${code ?? 'unknown'}).`);
  });
  await waitForBackend(port, token);
  return { port, token };
}

function createTray(): void {
  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, 'brand', 'icon.png')
    : path.join(app.getAppPath(), 'build', 'icon.png');
  const icon = nativeImage.createFromPath(iconPath);
  if (icon.isEmpty()) throw new Error(`Unable to load the application icon: ${iconPath}`);
  tray = new Tray(icon.resize({ width: 16, height: 16 }));
  tray.setToolTip('Local Agent Studio');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open Local Agent Studio', click: () => mainWindow?.show() },
    { type: 'separator' },
    { label: 'Quit', click: () => { isQuitting = true; app.quit(); } },
  ]));
  tray.on('double-click', () => mainWindow?.show());
}

async function createWindow(): Promise<void> {
  const connection = await startBackend();
  mainWindow = new BrowserWindow({
    width: 1420,
    height: 900,
    minWidth: 1040,
    minHeight: 700,
    backgroundColor: '#f5f3ee',
    title: 'Local Agent Studio',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      additionalArguments: [
        `--studio-api=http://127.0.0.1:${connection.port}`,
        `--studio-token=${connection.token}`,
      ],
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = process.env.VITE_DEV_SERVER_URL;
    if (!allowed || !url.startsWith(allowed)) event.preventDefault();
  });
  mainWindow.once('ready-to-show', () => mainWindow?.show());
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    await mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    await mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  }
  createTray();
}

app.on('before-quit', () => {
  isQuitting = true;
  if (backend && !backend.killed) backend.kill();
});
app.on('window-all-closed', () => {
  // The tray process intentionally remains available on Windows.
});
app.on('activate', () => mainWindow?.show());

void app.whenReady().then(createWindow).catch((error) => {
  console.error(error);
  app.quit();
});

import { access } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const required = [
  'dist/main/main.js',
  'dist/main/preload.cjs',
  'dist/renderer/index.html',
];

const missing = [];
for (const relativePath of required) {
  try {
    await access(path.resolve(process.cwd(), relativePath));
  } catch {
    missing.push(relativePath);
  }
}

if (missing.length > 0) {
  throw new Error(`Production build is incomplete. Missing: ${missing.join(', ')}`);
}

console.log(`Verified production artifacts: ${required.join(', ')}`);

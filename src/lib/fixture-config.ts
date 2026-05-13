import fs from 'fs';
import path from 'path';

export type FixtureCredentials = {
  baseUrl?: string;
  labName?: string;
  username?: string;
  password?: string;
};

function parseIniLike(contents: string): Record<string, string> {
  const out: Record<string, string> = {};
  const lines = contents.split(/\r?\n/g);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || line.startsWith(';')) continue;
    const idx = line.indexOf('=');
    if (idx < 0) continue;
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (!key) continue;
    out[key] = value;
  }
  return out;
}

export function loadFixtureCredentials(role: string = 'ADMIN'): FixtureCredentials {
  const iniPath = path.join(process.cwd(), 'fixtures', 'data.env.test.ini');
  let contents = '';
  try {
    contents = fs.readFileSync(iniPath, 'utf8');
  } catch {
    return {};
  }

  const kv = parseIniLike(contents);
  const roleKey = role.trim().toUpperCase().replace(/[^A-Z0-9]+/g, '_');

  return {
    baseUrl: kv.BASE_URL,
    labName: kv.LAB_NAME,
    username: kv[`${roleKey}_USERNAME`] ?? kv.ADMIN_USERNAME,
    password: kv[`${roleKey}_PASSWORD`] ?? kv.ADMIN_PASSWORD,
  };
}


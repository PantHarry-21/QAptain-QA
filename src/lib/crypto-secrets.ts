import crypto from 'crypto';

const ALG = 'aes-256-gcm';

function keyMaterial(): Buffer {
  const s =
    process.env.QAPTAIN_ENCRYPTION_KEY ||
    process.env.NEXTAUTH_SECRET ||
    'qaptain-dev-key-change-in-production';
  return crypto.createHash('sha256').update(s, 'utf8').digest();
}

export function encryptSecret(plain: string): string {
  const key = keyMaterial();
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv(ALG, key, iv);
  const enc = Buffer.concat([cipher.update(plain, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, enc]).toString('base64url');
}

export function decryptSecret(payload: string | null | undefined): string | null {
  if (!payload) return null;
  try {
    const buf = Buffer.from(payload, 'base64url');
    const iv = buf.subarray(0, 12);
    const tag = buf.subarray(12, 28);
    const data = buf.subarray(28);
    const key = keyMaterial();
    const decipher = crypto.createDecipheriv(ALG, key, iv);
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(data), decipher.final()]).toString('utf8');
  } catch {
    return null;
  }
}

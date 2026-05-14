import { getServerSession } from 'next-auth/next';
import { getAuthOptions } from '@/lib/auth';
import { NextResponse } from 'next/server';

export async function getSessionUserId(): Promise<string | null> {
  const session = await getServerSession(getAuthOptions());
  const id = session?.user && 'id' in session.user ? (session.user as { id?: string }).id : undefined;
  return id || null;
}

export async function requireSessionUserId(): Promise<string> {
  const id = await getSessionUserId();
  if (!id) {
    throw new Error('UNAUTHORIZED');
  }
  return id;
}

export function unauthorizedResponse() {
  return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
}

export function forbiddenResponse() {
  return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
}

export function serviceUnavailable(message: string) {
  return NextResponse.json({ error: message }, { status: 503 });
}

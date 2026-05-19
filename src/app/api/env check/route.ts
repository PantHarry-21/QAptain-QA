// app/api/env-check/route.ts
// This endpoint should only be available in development
import { NextResponse } from 'next/server';

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  // Only allow in development
  if (process.env.NODE_ENV !== 'development') {
    return NextResponse.json(
      { error: 'Not available in production' },
      { status: 403 }
    );
  }

  const ok = (k: string) => Boolean(process.env[k]);
  return NextResponse.json({
    NEXTAUTH_URL: ok("NEXTAUTH_URL"),
    NEXTAUTH_SECRET: ok("NEXTAUTH_SECRET"),
    DATABASE_URL: ok("DATABASE_URL"),
  });
}

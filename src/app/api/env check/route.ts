// app/api/env-check/route.ts
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function GET() {
  const ok = (k: string) => Boolean(process.env[k]);
  return new Response(JSON.stringify({
    NEXTAUTH_URL: ok("NEXTAUTH_URL"),
    NEXTAUTH_SECRET: ok("NEXTAUTH_SECRET"),
    DATABASE_URL: ok("DATABASE_URL"),
  }, null, 2), { headers: { "content-type": "application/json" } });
}

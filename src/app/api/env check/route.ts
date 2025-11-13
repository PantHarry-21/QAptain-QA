// app/api/env-check/route.ts
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function GET() {
  const ok = (k: string) => Boolean(process.env[k]);
  return new Response(JSON.stringify({
    NEXTAUTH_URL: ok("NEXTAUTH_URL"),
    NEXTAUTH_SECRET: ok("NEXTAUTH_SECRET"),
    SUPABASE_URL: ok("SUPABASE_URL"),
    NEXT_PUBLIC_SUPABASE_ANON_KEY: ok("NEXT_PUBLIC_SUPABASE_ANON_KEY"),
    SUPABASE_SERVICE_ROLE_KEY: ok("SUPABASE_SERVICE_ROLE_KEY"),
  }, null, 2), { headers: { "content-type": "application/json" } });
}

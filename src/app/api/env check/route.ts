// app/api/env-check/route.ts
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const ok = (k: string) => Boolean(process.env[k]);
  return new Response(
    JSON.stringify(
      {
        NEXTAUTH_URL: ok("NEXTAUTH_URL"),
        NEXTAUTH_SECRET: ok("NEXTAUTH_SECRET"),
        // Add any other vars you expect:
        // SUPABASE_URL: ok("SUPABASE_URL"), etc.
      },
      null,
      2
    ),
    { headers: { "content-type": "application/json" } }
  );
}

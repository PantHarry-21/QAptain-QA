export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const ok = (k: string) => Boolean(process.env[k]);

  const keys = [
    "NEXTAUTH_URL",
    "NEXTAUTH_SECRET",
    "PRODUCTION_NEXT_SUPABASE_URL",
    "PRODUCTION_PUBLIC_SUPABASE_URL",
    "PRODUCTION_NEXT_PUBLIC_SUPABASE_URL",
    "PRODUCTION_SUPABASE_URL",
    "SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_URL",
    "PRODUCTION_PUBLIC_SUPABASE_ANON_KEY",
    "PRODUCTION_NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "SUPABASE_ANON_KEY",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "PRODUCTION_SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    // Neon database variables
    "QAPTAIN_URL",
    "QAPTAIN_ANON_KEY",
    "QAPTAIN_SERVICE_ROLE_KEY",
    "NEON_URL",
    "NEON_ANON_KEY",
    "NEON_SERVICE_ROLE_KEY",
  ];

  const result: Record<string, boolean> = {};
  for (const key of keys) {
    result[key] = ok(key);
  }

  return new Response(JSON.stringify(result, null, 2), {
    headers: { "content-type": "application/json" },
  });
}


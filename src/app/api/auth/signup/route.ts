// app/api/auth/signup/route.ts
import "server-only";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

// Lazy helpers (no module-scope env access or clients)
function getSupabaseAnon() {
  // Use SUPABASE_URL if available, fallback to NEXT_PUBLIC_SUPABASE_URL (same value)
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anon) return null;
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { createClient } = require("@supabase/supabase-js");
  return createClient(url, anon);
}

function getSupabaseAdmin() {
  // Use SUPABASE_URL if available, fallback to NEXT_PUBLIC_SUPABASE_URL (same value)
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const service = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !service) return null;
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { createClient } = require("@supabase/supabase-js");
  return createClient(url, service);
}

function makeActivationToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
}

export async function POST(req: Request) {
  try {
    const { firstName, lastName, email, password } = await req.json().catch(() => ({} as any));

    if (!firstName || !lastName || !email || !password) {
      return NextResponse.json({ error: "All fields are required" }, { status: 400 });
    }

    const supabase = getSupabaseAnon();
    if (!supabase) {
      return NextResponse.json(
        { error: "Server misconfigured: SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) or NEXT_PUBLIC_SUPABASE_ANON_KEY missing" },
        { status: 500 }
      );
    }

    // 1) Sign up via ANON key (correct for auth flows)
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          first_name: firstName,
          last_name: lastName,
        },
        // emailRedirectTo: `${new URL(req.url).origin}/auth/callback`, // if you use Supabase email confirm
      },
    });

    if (error) {
      console.error("[signup] supabase.auth.signUp error:", error);
      return NextResponse.json({ error: error.message }, { status: error.status || 400 });
    }

    // If the email exists already, Supabase returns user but identities = []
    if (data?.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
      return NextResponse.json({ error: "User with this email already exists" }, { status: 409 });
    }

    const userId = data?.user?.id;

    // 2) OPTIONAL: if you run your own activation flow (/api/auth/activate/[token]),
    // create & store an activation token on your `users` table
    const admin = getSupabaseAdmin();
    if (admin && userId) {
      const token = makeActivationToken();
      const { error: upsertErr } = await admin
        .from("users")
        .upsert(
          {
            id: userId,
            email,
            first_name: firstName,
            last_name: lastName,
            activation_token: token,
            email_verified: null,
          },
          { onConflict: "id" }
        );

      if (upsertErr) {
        console.warn("[signup] users upsert warning:", upsertErr);
      }

      // TODO: send activation email with link:
      // `${new URL(req.url).origin}/api/auth/activate/${token}`
    }

    return NextResponse.json(
      { message: "User registered successfully. Please check your email for activation link." },
      { status: 201 }
    );
  } catch (err: any) {
    console.error("[signup] error:", err);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

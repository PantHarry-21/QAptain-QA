// app/api/auth/signup/route.ts
import "server-only";
import { NextResponse } from "next/server";
import { getSupabaseUrl, getSupabaseAnonKey, getSupabaseServiceRoleKey } from "@/lib/supabase";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

// Lazy helpers (no module-scope env access or clients)
function getSupabaseAnon() {
  // Use environment-aware Supabase credentials
  const url = getSupabaseUrl();
  const anon = getSupabaseAnonKey();
  if (!url || !anon) return null;
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { createClient } = require("@supabase/supabase-js");
  return createClient(url, anon);
}

function getSupabaseAdmin() {
  // Use environment-aware Supabase credentials
  const url = getSupabaseUrl();
  const service = getSupabaseServiceRoleKey();
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
        { error: "Server misconfigured: Supabase credentials missing. Please check your environment variables." },
        { status: 500 }
      );
    }

    // 1) Sign up via ANON key (correct for auth flows)
    // Get the base URL - use NEXTAUTH_URL in production, or fallback to request origin
    // This ensures production uses https://qaptain.vercel.app instead of localhost
    const baseUrl = process.env.NEXTAUTH_URL || new URL(req.url).origin;
    
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          first_name: firstName,
          last_name: lastName,
        },
        // Configure email redirect URL - Supabase will append token as query param
        // This fixes the localhost issue in production emails
        emailRedirectTo: `${baseUrl}/api/auth/activate`,
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

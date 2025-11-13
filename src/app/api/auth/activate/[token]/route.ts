// app/api/auth/activate/[token]/route.ts
import "server-only";
import { NextResponse } from "next/server";
import { getSupabaseUrl, getSupabaseServiceRoleKey } from "@/lib/supabase";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

function getSupabaseAdmin() {
  // Use environment-aware Supabase credentials
  const url = getSupabaseUrl();
  const serviceKey = getSupabaseServiceRoleKey();
  if (!url || !serviceKey) return null;

  // Lazy import to avoid module-scope side effects during build
  // and to keep this route Node-runtime friendly.
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { createClient } = require("@supabase/supabase-js");
  return createClient(url, serviceKey);
}

export async function GET(
  req: Request,
  context: { params: { token?: string } }
) {
  try {
    const url = new URL(req.url);
    const token = context.params?.token || url.searchParams.get("token") || "";

    if (!token) {
      return NextResponse.redirect(
        new URL("/login?error=Activation token missing", req.url)
      );
    }

    const supabase = getSupabaseAdmin();
    if (!supabase) {
      // Don't throw at build/import time—return a runtime error instead
      return NextResponse.redirect(
        new URL(
          "/login?error=Server misconfigured: Supabase credentials missing. Please check your environment variables.",
          req.url
        )
      );
    }

    // Look up the user by activation token
    const { data: user, error: findError } = await supabase
      .from("users")
      .select("*")
      .eq("activation_token", token)
      .single();

    if (findError || !user) {
      console.error("Activation error: User not found or token invalid", findError);
      return NextResponse.redirect(
        new URL("/login?error=Invalid or expired activation link", req.url)
      );
    }

    // Already verified?
    if (user.email_verified) {
      return NextResponse.redirect(
        new URL(
          "/login?message=Account already activated. Please log in.",
          req.url
        )
      );
    }

    // Activate user (clear token + mark timestamp)
    console.log(
      `Attempting to activate user ID: ${user.id} with email: ${user.email}`
    );
    const { error: updateError } = await supabase
      .from("users")
      .update({
        email_verified: new Date().toISOString(),
        activation_token: null,
      })
      .eq("id", user.id);

    if (updateError) {
      console.error("Error updating user for activation:", updateError);
      return NextResponse.redirect(
        new URL("/login?error=Failed to activate account", req.url)
      );
    }

    console.log(`Successfully activated user ID: ${user.id}`);
    return NextResponse.redirect(
      new URL(
        "/login?message=Account activated successfully! You can now log in.",
        req.url
      )
    );
  } catch (error) {
    console.error("Activation API error:", error);
    return NextResponse.redirect(
      new URL("/login?error=Internal server error", req.url)
    );
  }
}

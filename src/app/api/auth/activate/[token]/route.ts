// app/api/auth/activate/[token]/route.ts
import "server-only";
import { NextResponse } from "next/server";
import pool from "@/lib/db";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

export async function GET(
  req: Request,
  context: { params: { token?: string } }
) {
  try {
    const token = context.params?.token ?? "";

    if (!token) {
      return NextResponse.redirect(
        new URL("/login?error=Activation token missing", req.url)
      );
    }

    const client = await pool.connect();
    try {
      // Look up the user by activation token
      const { rows: users } = await client.query(
        "SELECT * FROM users WHERE activation_token = $1",
        [token]
      );
      const user = users[0];

      if (!user) {
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
      await client.query(
        "UPDATE users SET email_verified = NOW(), activation_token = NULL WHERE id = $1",
        [user.id]
      );

      console.log(`Successfully activated user ID: ${user.id}`);
      return NextResponse.redirect(
        new URL(
          "/login?message=Account activated successfully! You can now log in.",
          req.url
        )
      );
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Activation API error:", error);
    return NextResponse.redirect(
      new URL("/login?error=Internal server error", req.url)
    );
  }
}

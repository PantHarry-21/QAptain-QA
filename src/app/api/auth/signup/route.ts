// app/api/auth/signup/route.ts
import "server-only";
import { NextResponse } from "next/server";
import pool from "@/lib/db";
import bcrypt from "bcrypt";
import { v4 as uuidv4 } from 'uuid';
import { sendActivationEmail } from "@/lib/email";


export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

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

    const client = await pool.connect();
    try {
      // Check if user already exists
      const { rows: existingUsers } = await client.query(
        "SELECT id FROM users WHERE email = $1",
        [email]
      );

      if (existingUsers.length > 0) {
        return NextResponse.json({ error: "User with this email already exists" }, { status: 409 });
      }

      const hashedPassword = await bcrypt.hash(password, 10);
      const activationToken = makeActivationToken();
      const userId = uuidv4();


      await client.query(
        "INSERT INTO users (id, first_name, last_name, email, password, activation_token) VALUES ($1, $2, $3, $4, $5, $6)",
        [userId, firstName, lastName, email, hashedPassword, activationToken]
      );

      // Send activation email
      try {
        const activationUrl = `${new URL(req.url).origin}/api/auth/activate/${activationToken}`;
        await sendActivationEmail(email, firstName, activationToken, activationUrl);
        console.log(`[signup] Activation email sent to ${email}`);
      } catch (emailError: any) {
        console.error("[signup] Failed to send activation email:", emailError);
        // Don't fail the signup if email fails - user can request resend later
        // But log it for debugging
      }

      return NextResponse.json(
        { message: "User registered successfully. Please check your email for activation link." },
        { status: 201 }
      );
    } finally {
      client.release();
    }
  } catch (err: any) {
    console.error("[signup] error:", err);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

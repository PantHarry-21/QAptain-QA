
import "server-only";
import NextAuth from "next-auth";
import { NextResponse } from "next/server";
import { getAuthOptions } from "./../../../../lib/auth";

// Stop static analysis / caching and prefer Node
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

function getHandler() {
  const options = getAuthOptions();
  // Validate NEXTAUTH_SECRET at runtime (not build time)
  if (!options.secret && process.env.NODE_ENV === "production") {
    return NextResponse.json(
      {
        error:
          "NEXTAUTH_SECRET is required in production. Please set it in your environment variables.",
      },
      { status: 500 }
    );
  }
  return NextAuth(options);
}

export async function GET(req: Request) {
  const handler = getHandler();
  if (handler instanceof NextResponse) return handler;
  return handler(req);
}

export async function POST(req: Request) {
  const handler = getHandler();
  if (handler instanceof NextResponse) return handler;
  return handler(req);
}

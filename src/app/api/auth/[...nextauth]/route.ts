
import "server-only";
import NextAuth from "next-auth"
import { getAuthOptions } from "./../../../../lib/auth"

// Stop static analysis / caching and prefer Node
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

// Lazy initialization to avoid build-time errors
let handler: ReturnType<typeof NextAuth> | null = null;

function getHandler() {
  if (!handler) {
    const options = getAuthOptions();
    // Validate NEXTAUTH_SECRET at runtime (not build time)
    if (!options.secret && process.env.NODE_ENV === "production") {
      throw new Error(
        "NEXTAUTH_SECRET is required in production. Please set it in your environment variables."
      );
    }
    handler = NextAuth(options);
  }
  return handler;
}

export async function GET(req: Request) {
  return getHandler().GET(req);
}

export async function POST(req: Request) {
  return getHandler().POST(req);
}

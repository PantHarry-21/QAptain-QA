
import "server-only";
import NextAuth from "next-auth"
import { getAuthOptions } from "./../../../../lib/auth"

// Stop static analysis / caching and prefer Node
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

function getHandler() {
  const options = getAuthOptions();
  // Validate NEXTAUTH_SECRET at runtime (not build time)
  if (!options.secret && process.env.NODE_ENV === "production") {
    throw new Error(
      "NEXTAUTH_SECRET is required in production. Please set it in your environment variables."
    );
  }
  return NextAuth(options);
}

export async function GET(req: Request, context: any) {
  const handler = getHandler();
  return handler(req, context);
}

export async function POST(req: Request, context: any) {
  const handler = getHandler();
  return handler(req, context);
}

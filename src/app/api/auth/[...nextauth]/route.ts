
import "server-only";
import { NextResponse } from "next/server";

// Stop static analysis / caching and prefer Node
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

async function getHandler() {
  // During Next.js build (page data collection), avoid initializing NextAuth
  // or validating env. Return a trivial handler so build doesn't fail.
  // NEXT_PHASE is set by Next.js during build (e.g., 'phase-production-build').
  const phase = process.env.NEXT_PHASE;
  if (phase === "phase-production-build" || phase === "phase-development-build") {
    return (req: Request) => new Response("OK", { status: 200 });
  }

  // Defer heavy imports until after build-phase check
  const [{ default: NextAuth }, { getAuthOptions }] = await Promise.all([
    import("next-auth"),
    import("./../../../../lib/auth"),
  ]);

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
  const handler = await getHandler();
  if (handler instanceof NextResponse) return handler;
  return handler(req);
}

export async function POST(req: Request) {
  const handler = await getHandler();
  if (handler instanceof NextResponse) return handler;
  return handler(req);
}

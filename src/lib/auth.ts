import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import { createClient } from "@supabase/supabase-js";
import { SupabaseAdapter } from "@next-auth/supabase-adapter";

/** helpers: never throw at module scope */
const has = (k: string) => Boolean(process.env[k]);
const get = (k: string, fallback = "") => process.env[k] ?? fallback;
const warnMissing = (k: string) => {
  if (!has(k)) console.warn(`[auth] Missing env: ${k}`);
};

/**
 * Build-safe NextAuth options for v4.
 * - Adapter is optional and added only when required envs exist
 * - Credentials uses SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY (NOT service role)
 */
export const getAuthOptions = (): NextAuthOptions => {
  // Soft validations (warn only)
  ["NEXTAUTH_SECRET", "NEXTAUTH_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY"].forEach(
    warnMissing
  );

  /** Credentials provider (server-only) */
  const providers = [
    CredentialsProvider({
      name: "Credentials",
      credentials: {
        email: { label: "Email", type: "text" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        // Use SUPABASE_URL if available, fallback to NEXT_PUBLIC_SUPABASE_URL (same value)
        const SUPABASE_URL = get("SUPABASE_URL") || get("NEXT_PUBLIC_SUPABASE_URL");
        const SUPABASE_ANON_KEY = get("NEXT_PUBLIC_SUPABASE_ANON_KEY");

        if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
          console.warn("[auth] Missing SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) or NEXT_PUBLIC_SUPABASE_ANON_KEY in authorize()");
          return null;
        }
        if (!credentials?.email || !credentials?.password) return null;

        // Use ANON key for user auth flows
        const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

        const { data, error } = await supabase.auth.signInWithPassword({
          email: credentials.email,
          password: credentials.password,
        });

        if (error || !data?.user) return null;

        return {
          id: data.user.id,
          email: data.user.email,
          name: (data.user.user_metadata as any)?.full_name ?? data.user.email ?? "User",
        };
      },
    }),
  ];

  /** Optional Supabase adapter (requires service role) */
  // Use SUPABASE_URL if available, fallback to NEXT_PUBLIC_SUPABASE_URL (same value)
  const SUPABASE_URL = get("SUPABASE_URL") || get("NEXT_PUBLIC_SUPABASE_URL");
  const SUPABASE_SERVICE_ROLE_KEY = get("SUPABASE_SERVICE_ROLE_KEY");
  const adapter =
    SUPABASE_URL && SUPABASE_SERVICE_ROLE_KEY
      ? (SupabaseAdapter({
          url: SUPABASE_URL,
          secret: SUPABASE_SERVICE_ROLE_KEY,
        }) as any)
      : undefined;

  if (!adapter) {
    console.warn("[auth] SupabaseAdapter disabled: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY");
  }

  // NEXTAUTH_SECRET is required in production
  const secret = get("NEXTAUTH_SECRET");
  if (!secret && process.env.NODE_ENV === "production") {
    throw new Error(
      "NEXTAUTH_SECRET is required in production. Please set it in your environment variables."
    );
  }

  return {
    secret: secret || undefined,
    adapter,
    providers: providers as any,
    session: { strategy: "jwt" },
    callbacks: {
      async session({ session, token }) {
        // @ts-expect-error - augmenting session
        session.user.id = token.sub;
        // @ts-expect-error - custom field
        session.accessToken = (token as any).accessToken;
        return session;
      },
      async jwt({ token, user, account }) {
        if (account?.access_token) {
          (token as any).accessToken = account.access_token;
        }
        if (user?.id) {
          (token as any).id = user.id;
        }
        return token;
      },
    },
    pages: {
      signIn: "/login",
    },
  };
};

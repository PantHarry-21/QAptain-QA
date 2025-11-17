import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import pool from "./db";
import bcrypt from "bcrypt";

/** helpers: never throw at module scope (important for Vercel/build) */
const has = (k: string) => Boolean(process.env[k]);
const get = (k: string, fallback = "") => process.env[k] ?? fallback;
const warnMissing = (k: string) => {
  if (!has(k)) console.warn(`[auth] Missing env: ${k}`);
};

/**
 * Build-safe NextAuth options for v4.
 * - Uses Credentials provider against our own DB
 * - Uses JWT sessions (no DB adapter)
 */
export const getAuthOptions = (): NextAuthOptions => {
  // Soft validation – log missing envs instead of throwing at build time.
  ["NEXTAUTH_SECRET", "NEXTAUTH_URL", "DATABASE_URL"].forEach(warnMissing);

  /** Credentials provider (server-only) - database lookup is manual here */
  const providers = [
    CredentialsProvider({
      id: "credentials", // Explicit ID for NextAuth
      name: "Credentials",
      credentials: {
        email: { label: "Email", type: "text" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        console.log("[auth] Authorize called with email:", credentials?.email);
        
        if (!credentials?.email || !credentials?.password) {
          console.log("[auth] Missing credentials");
          return null;
        }

        const client = await pool.connect();
        try {
          console.log("[auth] Querying database for user:", credentials.email);
          const { rows } = await client.query(
            "SELECT id, email, password, first_name, last_name, email_verified FROM users WHERE email = $1",
            [credentials.email]
          );
          const user = rows[0];

          if (!user) {
            console.log("[auth] User not found in database");
            return null;
          }

          console.log("[auth] User found, comparing password");
          // Compare password asynchronously
          const passwordMatch = await bcrypt.compare(credentials.password, user.password);
          
          if (passwordMatch) {
            console.log("[auth] Password match! Creating user object");
            const fullName = user.first_name && user.last_name 
              ? `${user.first_name} ${user.last_name}` 
              : user.first_name || user.last_name || user.email || "User";
            const userObj = {
              id: user.id,
              email: user.email,
              name: fullName,
            };
            console.log("[auth] Returning user object:", { id: userObj.id, email: userObj.email, name: userObj.name });
            return userObj;
          } else {
            console.log("[auth] Password mismatch");
          }
        } catch (error) {
          console.error("[auth] Error during authorization:", error);
          if (error instanceof Error) {
            console.error("[auth] Error stack:", error.stack);
          }
        } finally {
          client.release();
        }

        console.log("[auth] Authorization failed");
        return null;
      },
    }),
  ];

  const secret = get("NEXTAUTH_SECRET");

  return {
    secret: secret || undefined,
    providers: providers as any,
    // Use JWT-based sessions (no database adapter for sessions)
    session: {
      strategy: "jwt",
    },
    debug: process.env.NODE_ENV === "development", // Enable debug in development
    trustHost: true, // Required for Next.js 15 App Router & Auth.js
    callbacks: {
      async session({ session, token }) {
        // Attach the user id from the JWT into the session object
        if (session.user && token.sub) {
          // @ts-expect-error augmenting session
          session.user.id = token.sub;
        }
        return session;
      },
      async jwt({ token, user }) {
        // On initial sign-in, copy the user id into the JWT
        if (user) {
          token.sub = (user as any).id;
        }
        return token;
      },
    },
    pages: {
      signIn: "/login",
    },
  };
};

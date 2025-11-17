import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import pool from "./db";
import bcrypt from "bcrypt";

/** helpers: never throw at module scope */
const has = (k: string) => Boolean(process.env[k]);
const get = (k: string, fallback = "") => process.env[k] ?? fallback;
const warnMissing = (k: string) => {
  if (!has(k)) console.warn(`[auth] Missing env: ${k}`);
};

/**
 * Build-safe NextAuth options for v4.
 * - Adapter is optional and added only when required envs exist
 * - Credentials uses the database connection pool
 */
export const getAuthOptions = (): NextAuthOptions => {
  // Hard validation for critical environment variables
  if (!process.env.NEXTAUTH_URL) {
    throw new Error(
      "Missing NEXTAUTH_URL environment variable. Please add NEXTAUTH_URL=http://localhost:3000 to your .env file."
    );
  }
  if (!process.env.NEXTAUTH_SECRET) {
    throw new Error(
      "Missing NEXTAUTH_SECRET environment variable. Please add a long, random string to your .env file. You can generate one at https://generate-secret.vercel.app/32"
    );
  }
  if (!process.env.DATABASE_URL) {
    throw new Error(
      "Missing DATABASE_URL environment variable. Please ensure your database connection string is in the .env file."
    );
  }

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

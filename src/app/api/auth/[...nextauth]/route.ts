import NextAuth from "next-auth"
import { getAuthOptions } from "@/lib/auth"

// This is the standard, simplified handler for NextAuth.js in the App Router.
// It replaces the complex custom wrapper.
// If an error occurs inside NextAuth, it should now be properly logged.

const handler = NextAuth(getAuthOptions());

export { handler as GET, handler as POST };
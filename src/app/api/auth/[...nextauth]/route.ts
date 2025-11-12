
import NextAuth from "next-auth"
import { getAuthOptions } from "./../../../../lib/auth"

export const dynamic = 'force-dynamic'
export const fetchCache = "force-no-store";

const handler = NextAuth(getAuthOptions())

export { handler as GET, handler as POST }

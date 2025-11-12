
import { SupabaseAdapter } from "@next-auth/supabase-adapter"
import CredentialsProvider from "next-auth/providers/credentials"
import { createClient } from "@supabase/supabase-js"
import { NextAuthOptions } from "next-auth"

export const getAuthOptions = (): NextAuthOptions => {
  return {
    providers: [
      CredentialsProvider({
        name: "Credentials",
        credentials: {
          email: { label: "Email", type: "text" },
          password: {  label: "Password", type: "password" }
        },
        async authorize(credentials) {
          const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!)
          if (!credentials?.email || !credentials?.password) {
            return null
          }

          const { data, error } = await supabase.auth.signInWithPassword({
            email: credentials.email,
            password: credentials.password,
          })

          if (error || !data.user) {
            return null
          }

          return {
              id: data.user.id,
              email: data.user.email,
              name: data.user.user_metadata.full_name,
          }
        }
      })
    ],
    adapter: SupabaseAdapter({
      url: process.env.NEXT_PUBLIC_SUPABASE_URL!,
      secret: process.env.SUPABASE_SERVICE_ROLE_KEY!,
    }),
    session: {
      strategy: "jwt",
    },
    callbacks: {
      async session({ session, token }) {
        session.user.id = token.sub
        session.accessToken = token.accessToken
        return session
      },
      async jwt({ token, user, account }) {
        if (account) {
          token.accessToken = account.access_token
        }
        if (user) {
          token.id = user.id
        }
        return token
      }
    },
    pages: {
      signIn: '/login',
    },
  }
}

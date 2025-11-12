
import { NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

export const dynamic = 'force-dynamic'

const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!)

export async function POST(req: Request) {
  try {
    const { firstName, lastName, email, password } = await req.json()

    if (!firstName || !lastName || !email || !password) {
      return NextResponse.json({ error: 'All fields are required' }, { status: 400 })
    }

    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          first_name: firstName,
          last_name: lastName,
        },
      },
    })

    if (error) {
      console.error('Supabase sign up error:', error)
      return NextResponse.json({ error: error.message }, { status: error.status || 500 })
    }
    
    if (data.user && data.user.identities && data.user.identities.length === 0) {
        return NextResponse.json({ error: 'User with this email already exists' }, { status: 409 })
    }


    return NextResponse.json({ message: 'User registered successfully. Please check your email for activation link.' }, { status: 201 })
  } catch (error) {
    console.error('Signup API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

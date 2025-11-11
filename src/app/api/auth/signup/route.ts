
import { NextResponse } from 'next/server'
import bcrypt from 'bcrypt'
import { createClient } from '@supabase/supabase-js'
import { v4 as uuidv4 } from 'uuid'

const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!)

export async function POST(req: Request) {
  try {
    const { firstName, lastName, email, password } = await req.json()

    if (!firstName || !lastName || !email || !password) {
      return NextResponse.json({ error: 'All fields are required' }, { status: 400 })
    }

    // Check if user already exists
    const { data: existingUser, error: findError } = await supabase
      .from('users')
      .select('id')
      .eq('email', email)
      .single()

    if (existingUser) {
      return NextResponse.json({ error: 'User with this email already exists' }, { status: 409 })
    }

    const hashedPassword = await bcrypt.hash(password, 10)
    const activationToken = uuidv4()

    const { data: newUser, error: insertError } = await supabase
      .from('users')
      .insert({
        first_name: firstName,
        last_name: lastName,
        email,
        password: hashedPassword,
        activation_token: activationToken,
        email_verified: null, // Will be set to timestamp upon activation
      })
      .select()
      .single()

    if (insertError) {
      console.error('Error inserting new user:', insertError)
      return NextResponse.json({ error: 'Failed to create user' }, { status: 500 })
    }

    // In a real application, you would send an email with this link
    const activationLink = `${process.env.NEXTAUTH_URL}/api/auth/activate/${activationToken}`
    console.log(`Activation Link for ${email}: ${activationLink}`)

    return NextResponse.json({ message: 'User registered successfully. Please check your email for activation link.' }, { status: 201 })
  } catch (error) {
    console.error('Signup API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

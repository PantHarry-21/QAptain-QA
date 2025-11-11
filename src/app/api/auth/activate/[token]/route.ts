
import { NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

export const dynamic = 'force-dynamic'

const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!)

export async function GET(req: Request, context: { params: { token: string } }) {
  try {
    const params = await context.params;
    const { token } = params;

    if (!token) {
      return NextResponse.redirect(new URL('/login?error=Activation token missing', req.url))
    }

    const { data: user, error: findError } = await supabase
      .from('users')
      .select('*')
      .eq('activation_token', token)
      .single()

    if (findError || !user) {
      console.error('Activation error: User not found or token invalid', findError)
      return NextResponse.redirect(new URL('/login?error=Invalid or expired activation link', req.url))
    }

    // Check if already verified
    if (user.email_verified) {
      return NextResponse.redirect(new URL('/login?message=Account already activated. Please log in.', req.url))
    }

    // Activate user
    console.log(`Attempting to activate user ID: ${user.id} with email: ${user.email}`);
    const { error: updateError } = await supabase
      .from('users')
      .update({
        email_verified: new Date().toISOString(),
        activation_token: null, // Clear the token after activation
      })
      .eq('id', user.id)

    if (updateError) {
      console.error('Error updating user for activation:', updateError);
      console.error('Supabase update error details:', updateError.message, updateError.details, updateError.hint);
      return NextResponse.redirect(new URL('/login?error=Failed to activate account', req.url));
    }
    console.log(`Successfully activated user ID: ${user.id}`);

    return NextResponse.redirect(new URL('/login?message=Account activated successfully! You can now log in.', req.url))
  } catch (error) {
    console.error('Activation API error:', error)
    return NextResponse.redirect(new URL('/login?error=Internal server error', req.url))
  }
}
